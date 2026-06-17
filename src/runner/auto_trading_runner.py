import time
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Dict

from src.broker.kis_account import KisAccount
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.config.bot_config import BotConfig
from src.config.env import Settings
from src.domain.position import Position, PositionState
from src.logs.trade_logger import get_trade_logger, write_trade_event
from src.risk.risk_manager import RiskManager, RiskState
from src.runner.dry_run_runner import calculate_order_quantity
from src.runner.market_hours import MarketHours
from src.strategy.advanced_signals import EntrySignal, ExitSignal, MarketFilter, SymbolFilter
from src.strategy.market_snapshot_builder import MarketSnapshotBuilder, parse_domestic_candles
from src.watchlist.watchlist_manager import WatchlistManager


@dataclass
class AutoTradingState:
    positions: Dict[str, Position] = field(default_factory=dict)
    daily_entry_count_by_symbol: Dict[str, int] = field(default_factory=dict)
    pending_order_symbols: set[str] = field(default_factory=set)
    partial_profit_taken_symbols: set[str] = field(default_factory=set)
    last_exit_at_by_symbol: Dict[str, datetime] = field(default_factory=dict)
    daily_loss_amount: int = 0
    consecutive_loss_count: int = 0


class AutoTradingRunner:
    def __init__(
        self,
        settings: Settings,
        bot_config: BotConfig,
        market_hours: MarketHours,
        domestic_market: KisMarket,
        domestic_account: KisAccount,
        domestic_order: KisOrder,
        watchlist_manager: WatchlistManager,
    ):
        self.settings = replace(
            settings,
            max_position_count=bot_config.risk.max_position_count,
            daily_max_loss_amount=bot_config.risk.max_daily_loss,
            daily_max_loss_rate=bot_config.risk.max_daily_loss_percent,
        )
        self.bot_config = bot_config
        self.market_hours = market_hours
        self.domestic_market = domestic_market
        self.domestic_account = domestic_account
        self.domestic_order = domestic_order
        self.watchlist_manager = watchlist_manager
        self.snapshot_builder = MarketSnapshotBuilder(bot_config.strategy)
        self.risk_manager = RiskManager(self.settings, bot_config.risk.max_daily_trade_count)
        market_filter = MarketFilter(bot_config)
        symbol_filter = SymbolFilter(bot_config)
        self.entry_signal = EntrySignal(bot_config, market_filter, symbol_filter)
        self.exit_signal = ExitSignal(bot_config)
        self.state = AutoTradingState()
        self.logger = get_trade_logger()
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.cycle_id = 0

    def run_forever(self, interval_seconds: int) -> None:
        """Run the automatic trading loop until the process is stopped.

        @param interval_seconds: Seconds between trading cycles.
        """
        self.logger.info("[AUTO START] dry_run=%s interval_seconds=%s", self.settings.dry_run, interval_seconds)
        while True:
            self.run_once()
            time.sleep(interval_seconds)

    def run_once(self) -> None:
        """Run one automatic domestic trading cycle."""
        self.cycle_id += 1
        self._reset_daily_state_if_needed()
        if self.bot_config.korea.enabled:
            if self.market_hours.is_domestic_open():
                self._run_domestic_cycle()
            else:
                self.logger.info("[AUTO WAIT] market=domestic")

    def _run_domestic_cycle(self) -> None:
        self._sync_domestic_positions()
        self.watchlist_manager.refresh("KR")
        symbols = self._get_domestic_cycle_symbols()
        for symbol in symbols:
            try:
                snapshot = self._build_domestic_snapshot(symbol)
                position = self.state.positions.get(symbol)
                if position is not None:
                    self._handle_domestic_sell(position, snapshot)
                    continue
                if not self.watchlist_manager.is_watchable("KR", symbol):
                    reason = self.watchlist_manager.get_exclude_reason("KR", symbol) or "not_in_watchlist"
                    self.logger.info("[BUY SKIP] market=KR symbol=%s name=%r skip_reason=%s", symbol, self._get_symbol_name("KR", symbol), reason)
                    self._write_skip_event("KR", symbol, self._get_symbol_name("KR", symbol), reason, snapshot=snapshot)
                    continue
                if not self._is_reentry_allowed(symbol):
                    self.logger.info("[BUY SKIP] market=domestic symbol=%s name=%r reason=REENTRY_COOLDOWN", symbol, self._get_symbol_name("KR", symbol))
                    self._write_skip_event("KR", symbol, self._get_symbol_name("KR", symbol), "REENTRY_COOLDOWN", snapshot=snapshot)
                    continue
                self._handle_domestic_buy(symbol, snapshot, self._is_domestic_new_buy_blocked())
            except Exception:
                self.logger.exception("[AUTO DOMESTIC CYCLE FAILED] symbol=%s", symbol)

    def _handle_domestic_buy(self, symbol: str, snapshot, is_new_buy_blocked: bool = False) -> None:
        name = self._get_symbol_name("KR", symbol)
        signal = self.entry_signal.evaluate("KR", snapshot, self._position_state(), self._risk_state(), self.risk_manager)
        self.logger.info("[BUY CHECK] market=domestic symbol=%s name=%r signal=%s", symbol, name, signal)
        self._write_strategy_decision("BUY", "KR", symbol, name, signal, snapshot)
        if not signal.allowed:
            return
        if is_new_buy_blocked:
            self.logger.info("[BUY SKIP] market=domestic symbol=%s name=%r reason=NEW_BUY_TIME_BLOCKED", symbol, name)
            self._write_skip_event("KR", symbol, name, "NEW_BUY_TIME_BLOCKED", snapshot=snapshot)
            return
        available_cash = self.domestic_account.get_available_cash(symbol)
        quantity = calculate_order_quantity(
            snapshot.current_price,
            available_cash,
            self.bot_config.risk.max_buy_amount_per_trade,
            self.settings.force_quantity,
        )
        if quantity < 1:
            self.logger.info("[BUY SKIP] market=domestic symbol=%s name=%r reason=NO_ORDER_QUANTITY available_cash=%s", symbol, name, available_cash)
            self._write_skip_event("KR", symbol, name, "NO_ORDER_QUANTITY", {"available_cash": available_cash}, snapshot)
            return
        self._place_domestic_buy(symbol, quantity, snapshot.current_price)

    def _handle_domestic_sell(self, position: Position, snapshot) -> None:
        signal = self.exit_signal.evaluate(
            position,
            snapshot,
            partial_taken=position.symbol in self.state.partial_profit_taken_symbols,
        )
        if self._is_domestic_force_sell_time():
            signal = signal.__class__("SELL", True, "FORCE_SELL_BEFORE_CLOSE", signal.details)
        self.logger.info("[SELL CHECK] market=domestic symbol=%s name=%r signal=%s", position.symbol, self._get_symbol_name("KR", position.symbol), signal)
        self._write_strategy_decision("SELL", "KR", position.symbol, self._get_symbol_name("KR", position.symbol), signal, snapshot)
        if signal.allowed:
            self._place_domestic_exit(position.symbol, position.quantity, signal.reason)

    def _place_domestic_buy(self, symbol: str, quantity: int, price: int) -> None:
        self.state.pending_order_symbols.add(symbol)
        try:
            response = self.domestic_order.buy_market(symbol, quantity)
            self.state.daily_entry_count_by_symbol[symbol] = self.state.daily_entry_count_by_symbol.get(symbol, 0) + 1
            self.state.positions[symbol] = Position(symbol=symbol, quantity=quantity, average_price=price, entry_time=datetime.now())
            self.logger.info("[BUY DONE] market=KR symbol=%s name=%r entry_price=%s quantity=%s response=%s", symbol, self._get_symbol_name("KR", symbol), price, quantity, response)
            write_trade_event(
                "order_filled",
                {
                    **self._event_context("KR", symbol, self._get_symbol_name("KR", symbol)),
                    "side": "BUY",
                    "order_type": "MARKET",
                    "decision_price": price,
                    "entry_price": price,
                    "requested_quantity": quantity,
                    "filled_quantity": None,
                    "filled_price": None,
                    "order_result": response,
                    "dry_run": self.settings.dry_run,
                },
            )
        finally:
            self.state.pending_order_symbols.discard(symbol)

    def _place_domestic_exit(self, symbol: str, quantity: int, reason: str) -> None:
        sell_quantity = self._exit_quantity(symbol, quantity, reason)
        if sell_quantity < 1:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=NO_SELL_QUANTITY", symbol)
            self._write_skip_event("KR", symbol, self._get_symbol_name("KR", symbol), "NO_SELL_QUANTITY")
            return
        self.state.pending_order_symbols.add(symbol)
        try:
            response = self.domestic_order.sell_market(symbol, sell_quantity)
            self._update_position_after_exit(symbol, sell_quantity, reason)
            self.logger.info("[SELL DONE] market=KR symbol=%s name=%r quantity=%s reason=%s response=%s", symbol, self._get_symbol_name("KR", symbol), sell_quantity, reason, response)
            write_trade_event(
                "order_filled",
                {
                    **self._event_context("KR", symbol, self._get_symbol_name("KR", symbol)),
                    "side": "SELL",
                    "order_type": "MARKET",
                    "exit_reason": reason,
                    "requested_quantity": sell_quantity,
                    "filled_quantity": None,
                    "filled_price": None,
                    "order_result": response,
                    "dry_run": self.settings.dry_run,
                },
            )
        finally:
            self.state.pending_order_symbols.discard(symbol)

    def _build_domestic_snapshot(self, symbol: str):
        rows = self.domestic_market.get_minute_chart(symbol)
        candles = parse_domestic_candles(rows)
        price = self.domestic_market.get_current_price(symbol)
        orderbook = self.domestic_market.get_orderbook(symbol)
        return self.snapshot_builder.build(symbol, candles, price, float(orderbook["spread_rate"]))

    def _get_domestic_cycle_symbols(self) -> list[str]:
        symbols = list(dict.fromkeys(self.watchlist_manager.get_symbols("KR") + list(self.state.positions)))
        return symbols

    def _sync_domestic_positions(self) -> None:
        for row in self.domestic_account.get_balance():
            symbol = str(row.get("pdno") or row.get("prdt_code") or "")
            quantity = _to_int(row.get("hldg_qty") or row.get("ord_psbl_qty") or 0)
            average_price = _to_int(row.get("pchs_avg_pric") or row.get("avg_prvs") or 0)
            if symbol and quantity > 0 and average_price > 0:
                self.state.positions.setdefault(symbol, Position(symbol, quantity, average_price, datetime.now()))

    def _position_state(self) -> PositionState:
        return PositionState(positions=tuple(self.state.positions.values()))

    def _risk_state(self) -> RiskState:
        return RiskState(
            current_position_count=len(self.state.positions),
            daily_loss_rate=0.0,
            daily_loss_amount=self.state.daily_loss_amount,
            consecutive_loss_count=self.state.consecutive_loss_count,
            daily_entry_count_by_symbol=dict(self.state.daily_entry_count_by_symbol),
            pending_order_symbols=set(self.state.pending_order_symbols),
            held_symbols=set(self.state.positions.keys()),
        )

    def _write_strategy_decision(self, side: str, market: str, symbol: str, name: str | None, signal, snapshot) -> None:
        write_trade_event(
            "strategy_decision",
            {
                **self._event_context(market, symbol, name),
                "side": side,
                "strategy_name": self.bot_config.strategy.name,
                "strategy_version": None,
                "applied_config": self._strategy_config_payload(),
                "market_snapshot": self._market_snapshot_payload(snapshot),
                "decision": {
                    "action": signal.signal,
                    "allowed": signal.allowed,
                    "reason": signal.reason,
                    "matched_conditions": list(signal.details.get("matched_conditions", ())),
                    "failed_conditions": list(signal.details.get("failed_conditions", ())),
                    "skip_reason": None if signal.allowed else signal.reason,
                    "entry_reason": signal.reason if side == "BUY" and signal.allowed else None,
                    "exit_reason": signal.reason if side == "SELL" and signal.allowed else None,
                },
                "strategy_values": dict(signal.details),
                "risk_snapshot": self._risk_snapshot_payload(),
                "dry_run": self.settings.dry_run,
            },
        )

    def _write_skip_event(self, market: str, symbol: str, name: str | None, reason: str, extra: dict | None = None, snapshot=None) -> None:
        payload = {
            **self._event_context(market, symbol, name),
            "reason": reason,
            "risk_snapshot": self._risk_snapshot_payload(),
            "dry_run": self.settings.dry_run,
        }
        if snapshot is not None:
            payload["market_snapshot"] = self._market_snapshot_payload(snapshot)
        if extra:
            payload.update(extra)
        write_trade_event("order_skipped", payload)

    def _event_context(self, market: str, symbol: str | None = None, name: str | None = None) -> dict:
        return {
            "run_id": self.run_id,
            "cycle_id": self.cycle_id,
            "market": market,
            "session": "regular" if self.market_hours.is_domestic_open() else "closed",
            "bot_status": "running",
            "symbol": symbol,
            "symbol_name": name,
        }

    def _strategy_config_payload(self) -> dict:
        strategy = self.bot_config.strategy
        risk = self.bot_config.risk
        return {
            "volume_multiplier": strategy.volume_multiplier,
            "breakout_window_minutes": strategy.breakout_window_minutes,
            "volume_lookback_minutes": strategy.volume_lookback_minutes,
            "vwap_hold_candles": strategy.vwap_hold_candles,
            "vwap_entry_price_ratio": strategy.vwap_entry_price_ratio,
            "max_daily_rise_percent": strategy.max_daily_rise_percent,
            "min_execution_strength": strategy.min_execution_strength,
            "max_spread_percent": strategy.max_spread_percent,
            "max_upper_wick_percent": strategy.max_upper_wick_percent,
            "market_down_block_threshold_percent": strategy.market_down_block_threshold_percent,
            "take_profit_percent": risk.take_profit_percent,
            "second_take_profit_percent": risk.second_take_profit_percent,
            "stop_loss_percent": risk.stop_loss_percent,
            "stale_position_minutes": risk.stale_position_minutes,
            "stale_position_min_profit_percent": risk.stale_position_min_profit_percent,
        }

    def _market_snapshot_payload(self, snapshot) -> dict:
        return {
            "symbol": snapshot.symbol,
            "current_price": snapshot.current_price,
            "vwap": snapshot.vwap,
            "vwap_gap": _rate_gap(snapshot.current_price, snapshot.vwap),
            "volume": snapshot.one_minute_volume,
            "one_minute_volume": snapshot.one_minute_volume,
            "avg_volume": snapshot.previous_five_minute_average_volume,
            "previous_five_minute_average_volume": snapshot.previous_five_minute_average_volume,
            "volume_ratio": _safe_ratio(snapshot.one_minute_volume, snapshot.previous_five_minute_average_volume),
            "recent_high": snapshot.recent_high,
            "price_breakout_threshold": snapshot.recent_high,
            "daily_rise_rate": snapshot.daily_rise_rate,
            "trade_value": snapshot.trade_value,
            "spread_rate": snapshot.spread_rate,
            "previous_candle_drop_rate": snapshot.previous_candle_drop_rate,
            "execution_strength": snapshot.execution_strength,
            "vwap_hold_candle_count": snapshot.vwap_hold_candle_count,
            "upper_wick_rate": snapshot.upper_wick_rate,
            "market_direction_rate": snapshot.market_direction_rate,
            "volume_declining": snapshot.volume_declining,
            "candles": [
                {
                    "timestamp": candle.timestamp,
                    "open_price": candle.open_price,
                    "high_price": candle.high_price,
                    "low_price": candle.low_price,
                    "close_price": candle.close_price,
                    "volume": candle.volume,
                }
                for candle in snapshot.candles
            ],
        }

    def _risk_snapshot_payload(self) -> dict:
        return {
            "daily_realized_pnl": None,
            "daily_loss_limit": self.settings.daily_max_loss_amount,
            "daily_loss_rate_limit": self.settings.daily_max_loss_rate,
            "daily_loss_amount": self.state.daily_loss_amount,
            "consecutive_losses": self.state.consecutive_loss_count,
            "max_positions": self.settings.max_position_count,
            "current_positions_count": len(self.state.positions),
            "held_symbols": sorted(self.state.positions),
            "pending_order_symbols": sorted(self.state.pending_order_symbols),
            "daily_entry_count_by_symbol": dict(self.state.daily_entry_count_by_symbol),
            "kill_switch_status": "off",
        }

    def _is_domestic_new_buy_blocked(self) -> bool:
        now = datetime.now(self.market_hours.korea_tz)
        close_time = _parse_hhmm(self.bot_config.korea.regular_close, now)
        if now >= close_time - timedelta(minutes=self.bot_config.korea.stop_new_buy_before_close_minutes):
            return True
        return not _is_in_entry_windows(now, self.bot_config.korea.entry_windows)

    def _is_domestic_force_sell_time(self) -> bool:
        now = datetime.now(self.market_hours.korea_tz)
        close_time = _parse_hhmm(self.bot_config.korea.regular_close, now)
        return now >= close_time - timedelta(minutes=self.bot_config.korea.force_sell_before_close_minutes)

    def _is_reentry_allowed(self, symbol: str) -> bool:
        last_exit_at = self.state.last_exit_at_by_symbol.get(symbol)
        if last_exit_at is None:
            return True
        return datetime.now() - last_exit_at >= timedelta(minutes=self.bot_config.risk.reentry_cooldown_minutes)

    def _get_symbol_name(self, market: str, symbol: str) -> str | None:
        return self.watchlist_manager.get_symbol_name(market, symbol)

    def _exit_quantity(self, symbol: str, quantity: int, reason: str) -> int:
        if reason == "FIRST_TAKE_PROFIT" and symbol not in self.state.partial_profit_taken_symbols:
            return max(1, int(quantity * self.bot_config.risk.partial_take_profit_ratio))
        return quantity

    def _update_position_after_exit(self, symbol: str, sell_quantity: int, reason: str) -> None:
        position = self.state.positions.get(symbol)
        if position is None:
            return
        remaining_quantity = position.quantity - sell_quantity
        if reason == "FIRST_TAKE_PROFIT" and remaining_quantity > 0:
            self.state.partial_profit_taken_symbols.add(symbol)
            self.state.positions[symbol] = Position(symbol, remaining_quantity, position.average_price, position.entry_time)
            return
        self.state.positions.pop(symbol, None)
        self.state.partial_profit_taken_symbols.discard(symbol)
        self.state.last_exit_at_by_symbol[symbol] = datetime.now()

    def _reset_daily_state_if_needed(self) -> None:
        today = datetime.now().date()
        if getattr(self, "_state_date", today) != today:
            self.state = AutoTradingState()
        self._state_date = today

def _parse_hhmm(value: str, now: datetime) -> datetime:
    hour_text, minute_text = value.split(":", 1)
    return now.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)


def _is_in_entry_windows(now: datetime, windows: tuple[tuple[str, str], ...]) -> bool:
    for start, end in windows:
        if _parse_hhmm(start, now) <= now < _parse_hhmm(end, now):
            return True
    return False


def _to_int(value) -> int:
    if value in (None, ""):
        return 0
    return int(float(str(value).replace(",", "")))


def _rate_gap(current_price: int | float, base_price: int | float) -> float | None:
    if base_price <= 0:
        return None
    return ((current_price - base_price) / base_price) * 100


def _safe_ratio(value: int | float, base_value: int | float) -> float | None:
    if base_value <= 0:
        return None
    return value / base_value
