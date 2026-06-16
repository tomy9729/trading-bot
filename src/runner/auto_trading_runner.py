import time
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Dict

from src.broker.kis_account import KisAccount
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.broker.kis_overseas_account import KisOverseasAccount
from src.broker.kis_overseas_market import KisOverseasMarket
from src.broker.kis_overseas_order import KisOverseasOrder
from src.config.bot_config import BotConfig, UsWatchItem
from src.config.env import Settings
from src.domain.position import Position, PositionState
from src.logs.trade_logger import get_trade_logger
from src.risk.risk_manager import RiskManager, RiskState
from src.runner.dry_run_runner import calculate_order_quantity
from src.runner.market_hours import MarketHours
from src.strategy.advanced_signals import EntrySignal, ExitSignal, MarketFilter, SymbolFilter
from src.strategy.market_snapshot_builder import MarketSnapshotBuilder, parse_domestic_candles, parse_overseas_candles
from src.watchlist.watchlist_manager import WatchlistManager


@dataclass
class AutoTradingState:
    positions: Dict[str, Position] = field(default_factory=dict)
    daily_entry_count_by_symbol: Dict[str, int] = field(default_factory=dict)
    pending_order_symbols: set[str] = field(default_factory=set)
    partial_profit_taken_symbols: set[str] = field(default_factory=set)
    last_exit_at_by_symbol: Dict[str, datetime] = field(default_factory=dict)
    us_invested_krw_by_symbol: Dict[str, int] = field(default_factory=dict)
    us_total_invested_krw: int = 0
    daily_loss_amount: int = 0
    consecutive_loss_count: int = 0
    stopped_new_order: bool = False


class AutoTradingRunner:
    def __init__(
        self,
        settings: Settings,
        bot_config: BotConfig,
        market_hours: MarketHours,
        domestic_market: KisMarket,
        domestic_account: KisAccount,
        domestic_order: KisOrder,
        overseas_market: KisOverseasMarket,
        overseas_account: KisOverseasAccount,
        overseas_order: KisOverseasOrder,
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
        self.overseas_market = overseas_market
        self.overseas_account = overseas_account
        self.overseas_order = overseas_order
        self.watchlist_manager = watchlist_manager
        self.snapshot_builder = MarketSnapshotBuilder(bot_config.strategy)
        self.risk_manager = RiskManager(self.settings, bot_config.risk.max_daily_trade_count)
        market_filter = MarketFilter(bot_config)
        symbol_filter = SymbolFilter(bot_config)
        self.entry_signal = EntrySignal(bot_config, market_filter, symbol_filter)
        self.exit_signal = ExitSignal(bot_config)
        self.state = AutoTradingState()
        self.logger = get_trade_logger()

    def run_forever(self, interval_seconds: int) -> None:
        """Run the automatic trading loop until the process is stopped.

        @param interval_seconds: Seconds between trading cycles.
        """
        self.logger.info("[AUTO START] dry_run=%s interval_seconds=%s", self.settings.dry_run, interval_seconds)
        while True:
            self.run_once()
            time.sleep(interval_seconds)

    def run_once(self) -> None:
        """Run one automatic trading cycle for enabled markets."""
        self._reset_daily_state_if_needed()
        if self.bot_config.korea.enabled:
            if self.market_hours.is_domestic_open():
                self._run_domestic_cycle()
            else:
                self.logger.info("[AUTO WAIT] market=domestic")
        if self.bot_config.us.enabled:
            if self.market_hours.is_us_open():
                self._run_us_cycle()
            else:
                self.logger.info("[AUTO WAIT] market=us")

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
                    self.logger.info("[BUY SKIP] market=KR symbol=%s skip_reason=%s", symbol, reason)
                    continue
                if not self._is_reentry_allowed(symbol):
                    self.logger.info("[BUY SKIP] market=domestic symbol=%s reason=REENTRY_COOLDOWN", symbol)
                    continue
                self._handle_domestic_buy(symbol, snapshot, self._is_domestic_new_buy_blocked())
            except Exception:
                self.state.stopped_new_order = True
                self.logger.exception("[AUTO DOMESTIC CYCLE FAILED] symbol=%s", symbol)

    def _run_us_cycle(self) -> None:
        self._sync_us_positions()
        self.watchlist_manager.refresh("US")
        for item in self._get_us_cycle_items():
            try:
                snapshot = self._build_us_snapshot(item)
                position = self.state.positions.get(item.symbol)
                if position is not None:
                    self._handle_us_sell(item, position, snapshot)
                    continue
                if not self.watchlist_manager.is_watchable("US", item.symbol):
                    reason = self.watchlist_manager.get_exclude_reason("US", item.symbol) or "not_in_watchlist"
                    self.logger.info("[BUY SKIP] market=US symbol=%s skip_reason=%s", item.symbol, reason)
                    continue
                if not self._is_reentry_allowed(item.symbol):
                    self.logger.info("[BUY SKIP] market=us symbol=%s reason=REENTRY_COOLDOWN", item.symbol)
                    continue
                self._handle_us_buy(item, snapshot, self._is_us_new_buy_blocked())
            except Exception:
                self.state.stopped_new_order = True
                self.logger.exception("[AUTO US CYCLE FAILED] symbol=%s", item.symbol)

    def _handle_domestic_buy(self, symbol: str, snapshot, is_new_buy_blocked: bool = False) -> None:
        if self.state.stopped_new_order:
            self.logger.info("[BUY SKIP] market=domestic symbol=%s reason=NEW_ORDER_STOPPED", symbol)
            return
        signal = self.entry_signal.evaluate("KR", snapshot, self._position_state(), self._risk_state(), self.risk_manager)
        self.logger.info("[BUY CHECK] market=domestic symbol=%s signal=%s", symbol, signal)
        if not signal.allowed:
            return
        if is_new_buy_blocked:
            self.logger.info("[BUY SKIP] market=domestic symbol=%s reason=NEW_BUY_TIME_BLOCKED", symbol)
            return
        available_cash = self.domestic_account.get_available_cash(symbol)
        quantity = calculate_order_quantity(
            snapshot.current_price,
            available_cash,
            self.bot_config.risk.max_buy_amount_per_trade,
            self.settings.force_quantity,
        )
        if quantity < 1:
            self.logger.info("[BUY SKIP] market=domestic symbol=%s reason=NO_ORDER_QUANTITY available_cash=%s", symbol, available_cash)
            return
        self._place_domestic_buy(symbol, quantity, snapshot.current_price)

    def _handle_us_buy(self, item: UsWatchItem, snapshot, is_new_buy_blocked: bool = False) -> None:
        if self.state.stopped_new_order:
            self.logger.info("[BUY SKIP] market=us symbol=%s reason=NEW_ORDER_STOPPED", item.symbol)
            return
        signal = self.entry_signal.evaluate("US", snapshot, self._position_state(), self._risk_state(), self.risk_manager)
        self.logger.info("[BUY CHECK] market=us symbol=%s signal=%s", item.symbol, signal)
        if not signal.allowed:
            return
        if is_new_buy_blocked:
            self.logger.info("[BUY SKIP] market=us symbol=%s reason=NEW_BUY_TIME_BLOCKED", item.symbol)
            return
        available_cash = self.overseas_account.get_available_cash(item.symbol, snapshot.current_price, item.order_exchange)
        quantity = self._calculate_us_order_quantity(item.symbol, snapshot.current_price, available_cash)
        if quantity <= 0:
            self.logger.info("[BUY SKIP] market=us symbol=%s reason=NO_ORDER_QUANTITY available_cash=%s", item.symbol, available_cash)
            return
        self._place_us_buy(item, quantity, snapshot.current_price)

    def _handle_domestic_sell(self, position: Position, snapshot) -> None:
        signal = self.exit_signal.evaluate(
            position,
            snapshot,
            partial_taken=position.symbol in self.state.partial_profit_taken_symbols,
        )
        if self._is_domestic_force_sell_time():
            signal = signal.__class__("SELL", True, "FORCE_SELL_BEFORE_CLOSE", signal.details)
        self.logger.info("[SELL CHECK] market=domestic symbol=%s signal=%s", position.symbol, signal)
        if signal.allowed:
            self._place_domestic_exit(position.symbol, position.quantity, signal.reason)

    def _handle_us_sell(self, item: UsWatchItem, position: Position, snapshot) -> None:
        signal = self.exit_signal.evaluate(
            position,
            snapshot,
            partial_taken=position.symbol in self.state.partial_profit_taken_symbols,
        )
        self.logger.info("[SELL CHECK] market=us symbol=%s signal=%s", position.symbol, signal)
        if signal.allowed:
            self._place_us_exit(item, position.quantity, snapshot.current_price, signal.reason)

    def _place_domestic_buy(self, symbol: str, quantity: int, price: int) -> None:
        self.state.pending_order_symbols.add(symbol)
        try:
            response = self.domestic_order.buy_market(symbol, quantity)
            self.state.daily_entry_count_by_symbol[symbol] = self.state.daily_entry_count_by_symbol.get(symbol, 0) + 1
            self.state.positions[symbol] = Position(symbol=symbol, quantity=quantity, average_price=price, entry_time=datetime.now())
            self.logger.info("[BUY DONE] market=KR symbol=%s entry_price=%s quantity=%s response=%s", symbol, price, quantity, response)
        finally:
            self.state.pending_order_symbols.discard(symbol)

    def _place_domestic_exit(self, symbol: str, quantity: int, reason: str) -> None:
        sell_quantity = self._exit_quantity(symbol, quantity, reason)
        if sell_quantity < 1:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=NO_SELL_QUANTITY", symbol)
            return
        self.state.pending_order_symbols.add(symbol)
        try:
            response = self.domestic_order.sell_market(symbol, sell_quantity)
            self._update_position_after_exit(symbol, sell_quantity, reason)
            self.logger.info("[SELL DONE] market=KR symbol=%s quantity=%s reason=%s response=%s", symbol, sell_quantity, reason, response)
        finally:
            self.state.pending_order_symbols.discard(symbol)

    def _place_us_buy(self, item: UsWatchItem, quantity: Decimal, price: int | float) -> None:
        self.state.pending_order_symbols.add(item.symbol)
        try:
            if (
                quantity != quantity.to_integral_value()
                and not self.settings.dry_run
                and not self.bot_config.risk.us_fractional_order_enabled
            ):
                raise RuntimeError("US fractional order is calculated but live fractional API is not enabled.")
            response = self.overseas_order.buy_limit(item.symbol, quantity, float(price), item.order_exchange)
            self.state.daily_entry_count_by_symbol[item.symbol] = self.state.daily_entry_count_by_symbol.get(item.symbol, 0) + 1
            self.state.positions[item.symbol] = Position(symbol=item.symbol, quantity=float(quantity), average_price=price, entry_time=datetime.now())
            order_krw = min(
                self.bot_config.risk.us_order_amount_krw,
                self.bot_config.risk.us_total_test_capital_krw - self.state.us_total_invested_krw,
                self.bot_config.risk.us_max_symbol_exposure_krw - self.state.us_invested_krw_by_symbol.get(item.symbol, 0),
            )
            self.state.us_total_invested_krw += max(order_krw, 0)
            self.state.us_invested_krw_by_symbol[item.symbol] = self.state.us_invested_krw_by_symbol.get(item.symbol, 0) + max(order_krw, 0)
            self.logger.info("[BUY DONE] market=US symbol=%s entry_price=%s quantity=%s response=%s", item.symbol, price, quantity, response)
        finally:
            self.state.pending_order_symbols.discard(item.symbol)

    def _place_us_exit(self, item: UsWatchItem, quantity: int, price: int | float, reason: str) -> None:
        sell_quantity = self._exit_quantity(item.symbol, quantity, reason)
        if sell_quantity < 1:
            self.logger.info("[SELL SKIP] market=US symbol=%s reason=NO_SELL_QUANTITY", item.symbol)
            return
        self.state.pending_order_symbols.add(item.symbol)
        try:
            response = self.overseas_order.sell_limit(item.symbol, sell_quantity, float(price), item.order_exchange)
            self._update_position_after_exit(item.symbol, sell_quantity, reason)
            self.logger.info("[SELL DONE] market=US symbol=%s exit_price=%s quantity=%s reason=%s response=%s", item.symbol, price, sell_quantity, reason, response)
        finally:
            self.state.pending_order_symbols.discard(item.symbol)

    def _build_domestic_snapshot(self, symbol: str):
        rows = self.domestic_market.get_minute_chart(symbol)
        candles = parse_domestic_candles(rows)
        price = self.domestic_market.get_current_price(symbol)
        orderbook = self.domestic_market.get_orderbook(symbol)
        return self.snapshot_builder.build(symbol, candles, price, float(orderbook["spread_rate"]))

    def _build_us_snapshot(self, item: UsWatchItem):
        rows = self.overseas_market.get_minute_chart(item.symbol, item.quote_exchange)
        candles = parse_overseas_candles(rows)
        price = self.overseas_market.get_current_price(item.symbol, item.quote_exchange)
        orderbook = self.overseas_market.get_orderbook(item.symbol, item.quote_exchange)
        return self.snapshot_builder.build(item.symbol, candles, price, float(orderbook["spread_rate"]))

    def _get_domestic_cycle_symbols(self) -> list[str]:
        domestic_position_symbols = [symbol for symbol in self.state.positions if _is_domestic_symbol(symbol)]
        symbols = list(dict.fromkeys(self.watchlist_manager.get_symbols("KR") + domestic_position_symbols))
        return symbols

    def _get_us_cycle_items(self) -> list[UsWatchItem]:
        item_by_symbol = {item.symbol: item for item in self.watchlist_manager.get_us_items()}
        for symbol in self.state.positions:
            if _is_domestic_symbol(symbol):
                continue
            item_by_symbol.setdefault(symbol, UsWatchItem(symbol=symbol, quote_exchange="NAS", order_exchange="NASD"))
        return list(item_by_symbol.values())

    def _sync_domestic_positions(self) -> None:
        for row in self.domestic_account.get_balance():
            symbol = str(row.get("pdno") or row.get("prdt_code") or "")
            quantity = _to_int(row.get("hldg_qty") or row.get("ord_psbl_qty") or 0)
            average_price = _to_int(row.get("pchs_avg_pric") or row.get("avg_prvs") or 0)
            if symbol and quantity > 0 and average_price > 0:
                self.state.positions.setdefault(symbol, Position(symbol, quantity, average_price, datetime.now()))

    def _sync_us_positions(self) -> None:
        for item in self.bot_config.us.watchlist:
            for row in self.overseas_account.get_balance(item.order_exchange, "USD"):
                symbol = str(row.get("ovrs_pdno") or row.get("pdno") or "")
                quantity = _to_int(row.get("ovrs_cblc_qty") or row.get("hldg_qty") or 0)
                average_price = _to_int(float(row.get("pchs_avg_pric") or row.get("avg_unpr") or 0))
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

    def _is_domestic_new_buy_blocked(self) -> bool:
        now = datetime.now(self.market_hours.korea_tz)
        close_time = _parse_hhmm(self.bot_config.korea.regular_close, now)
        if now >= close_time - timedelta(minutes=self.bot_config.korea.stop_new_buy_before_close_minutes):
            return True
        return not _is_in_entry_windows(now, self.bot_config.korea.entry_windows)

    def _is_us_new_buy_blocked(self) -> bool:
        now = datetime.now(self.market_hours.korea_tz)
        if not self.market_hours.is_us_open(now):
            return True
        if now.time() >= _parse_time("22:30"):
            open_time = _parse_hhmm("22:30", now)
            close_time = _parse_hhmm("05:00", now + timedelta(days=1))
        else:
            open_time = _parse_hhmm("22:30", now - timedelta(days=1))
            close_time = _parse_hhmm("05:00", now)
        return (
            now < open_time + timedelta(minutes=self.bot_config.us.entry_start_after_open_minutes)
            or now >= close_time - timedelta(minutes=self.bot_config.us.entry_stop_before_close_minutes)
        )

    def _is_domestic_force_sell_time(self) -> bool:
        now = datetime.now(self.market_hours.korea_tz)
        close_time = _parse_hhmm(self.bot_config.korea.regular_close, now)
        return now >= close_time - timedelta(minutes=self.bot_config.korea.force_sell_before_close_minutes)

    def _is_reentry_allowed(self, symbol: str) -> bool:
        last_exit_at = self.state.last_exit_at_by_symbol.get(symbol)
        if last_exit_at is None:
            return True
        return datetime.now() - last_exit_at >= timedelta(minutes=self.bot_config.risk.reentry_cooldown_minutes)

    def _calculate_us_order_quantity(self, symbol: str, current_price: int | float, available_cash: float) -> Decimal:
        if current_price <= 0 or available_cash <= 0:
            return Decimal("0")
        if self.settings.force_quantity is not None:
            return Decimal(str(self.settings.force_quantity)) if current_price * self.settings.force_quantity <= available_cash else Decimal("0")
        if self.state.us_total_invested_krw >= self.bot_config.risk.us_total_test_capital_krw:
            return Decimal("0")
        if self.state.us_invested_krw_by_symbol.get(symbol, 0) >= self.bot_config.risk.us_max_symbol_exposure_krw:
            return Decimal("0")
        order_krw = min(
            self.bot_config.risk.us_order_amount_krw,
            self.bot_config.risk.us_total_test_capital_krw - self.state.us_total_invested_krw,
            self.bot_config.risk.us_max_symbol_exposure_krw - self.state.us_invested_krw_by_symbol.get(symbol, 0),
        )
        if order_krw <= 0:
            return Decimal("0")
        usd_amount = Decimal(str(order_krw)) / Decimal(str(self.bot_config.risk.us_assumed_usd_krw_rate))
        usd_amount = usd_amount * (Decimal("1") - Decimal(str(self.bot_config.risk.us_fee_buffer_rate)))
        price = Decimal(str(current_price))
        if self.bot_config.risk.us_order_mode == "whole_share_amount":
            return (usd_amount // price).quantize(Decimal("1"))
        if self.bot_config.risk.us_order_mode == "fractional_amount":
            return (usd_amount / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        raise RuntimeError(f"Unsupported US order mode: {self.bot_config.risk.us_order_mode}")

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


def _parse_time(value: str):
    hour_text, minute_text = value.split(":", 1)
    return datetime.now().time().replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)


def _is_in_entry_windows(now: datetime, windows: tuple[tuple[str, str], ...]) -> bool:
    for start, end in windows:
        if _parse_hhmm(start, now) <= now < _parse_hhmm(end, now):
            return True
    return False


def _to_int(value) -> int:
    if value in (None, ""):
        return 0
    return int(float(str(value).replace(",", "")))


def _is_domestic_symbol(symbol: str) -> bool:
    return len(symbol) == 6 and symbol.isdigit()
