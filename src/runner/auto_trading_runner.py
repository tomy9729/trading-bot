import time
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable

from src.broker.kis_account import KisAccount
from src.broker.kis_market import KisMarket
from src.config.bot_config import BotConfig
from src.config.env import Settings
from src.config.strategy_metadata import create_strategy_metadata
from src.db.repository import TradingRepository
from src.domain.order import MarketOrderGateway
from src.domain.position import Position, PositionState
from src.logs.trade_logger import get_trade_logger, write_trade_event
from src.risk.risk_manager import RiskManager, RiskState
from src.runner.auto_trading_state import AutoTradingState
from src.runner.dry_run_runner import calculate_order_quantity
from src.runner.market_hours import MarketHours
from src.services.order_execution_service import OrderExecutionService
from src.services.trading_account_service import TradingAccountService
from src.strategy.advanced_signals import EntrySignal, ExitSignal, MarketFilter, SymbolFilter
from src.strategy.market_snapshot_builder import MarketSnapshotBuilder, parse_domestic_candles
from src.watchlist.watchlist_manager import WatchlistManager


class AutoTradingRunner:
    def __init__(
        self,
        settings: Settings,
        bot_config: BotConfig,
        market_hours: MarketHours,
        domestic_market: KisMarket,
        domestic_account: KisAccount,
        domestic_order: MarketOrderGateway,
        watchlist_manager: WatchlistManager,
        trade_repository: TradingRepository | None = None,
    ):
        self.settings = replace(
            settings,
            max_position_count=bot_config.risk.max_position_count,
            daily_max_loss_amount=bot_config.risk.max_daily_loss,
            daily_max_loss_rate=bot_config.risk.max_daily_loss_percent,
        )
        self.bot_config = bot_config
        self.strategy_metadata = create_strategy_metadata(bot_config)
        self.market_hours = market_hours
        self.domestic_market = domestic_market
        self.domestic_account = domestic_account
        self.domestic_order = domestic_order
        self.watchlist_manager = watchlist_manager
        self.trade_repository = trade_repository
        self.snapshot_builder = MarketSnapshotBuilder(bot_config.strategy)
        self.risk_manager = RiskManager(
            self.settings,
            bot_config.risk.max_daily_trade_count,
            bot_config.risk.enforce_daily_loss_limit,
        )
        market_filter = MarketFilter(bot_config)
        symbol_filter = SymbolFilter(bot_config)
        self.entry_signal = EntrySignal(bot_config, market_filter, symbol_filter)
        self.exit_signal = ExitSignal(bot_config)
        self.state = AutoTradingState()
        self.logger = get_trade_logger()
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.cycle_id = 0
        self.account_service = TradingAccountService(
            self.settings,
            bot_config,
            domestic_account,
            trade_repository,
            self._call_with_retries,
            self._activate_safe_mode,
            self._activate_kill_switch,
            self._event_context,
            self.logger,
        )
        self.order_execution_service = OrderExecutionService(
            self.settings,
            bot_config,
            domestic_order,
            self.account_service,
            self._get_symbol_name,
            self._event_context,
            self._write_skip_event,
            self._activate_safe_mode,
            self.logger,
        )

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
        if not self.state.startup_recovered:
            self.recover_once()
        if self.bot_config.korea.enabled:
            if self.market_hours.is_domestic_open():
                self._run_domestic_cycle()
            else:
                self.logger.info("[AUTO WAIT] market=domestic")

    def recover_once(self, save_snapshot: bool = False) -> None:
        """Recover broker positions, open orders, executions, and local risk state.

        @param save_snapshot: Whether to save an account snapshot after recovery.
        @public
        @mutate: Updates runtime state and synchronized database rows without placing orders.
        """
        self.account_service.recover_startup_state(self.state)
        if save_snapshot and not self.state.safe_mode:
            self.account_service.save_account_snapshot(self.state, force=True)

    def _run_domestic_cycle(self) -> None:
        if not self._sync_domestic_positions():
            return
        self._sync_domestic_executions()
        self._save_account_snapshot()
        try:
            self._call_with_retries(lambda: self.watchlist_manager.refresh("KR"), "watchlist_refresh", "KR")
        except Exception:
            self._activate_safe_mode("WATCHLIST_REFRESH_FAILED")
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
            except Exception as exc:
                self.logger.exception("[AUTO DOMESTIC CYCLE FAILED] symbol=%s", symbol)
                write_trade_event(
                    "auto_cycle_failed",
                    {
                        **self._event_context("KR", symbol, self._get_symbol_name("KR", symbol)),
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                )

    def _handle_domestic_buy(self, symbol: str, snapshot, is_new_buy_blocked: bool = False) -> None:
        name = self._get_symbol_name("KR", symbol)
        if self.state.safe_mode:
            self.logger.info("[BUY SKIP] market=KR symbol=%s name=%r reason=SAFE_MODE_ACTIVE", symbol, name)
            self._write_skip_event("KR", symbol, name, "SAFE_MODE_ACTIVE", snapshot=snapshot)
            return
        if self._is_kill_switch_active():
            self.logger.info("[BUY SKIP] market=KR symbol=%s name=%r reason=KILL_SWITCH_ACTIVE", symbol, name)
            self._write_skip_event("KR", symbol, name, "KILL_SWITCH_ACTIVE", snapshot=snapshot)
            return
        if symbol in self.state.pending_buy_symbols:
            self.logger.info("[BUY SKIP] market=KR symbol=%s name=%r reason=PENDING_BUY_ORDER_EXISTS", symbol, name)
            self._write_skip_event("KR", symbol, name, "PENDING_BUY_ORDER_EXISTS", snapshot=snapshot)
            return
        if symbol in self.state.order_locked_symbols:
            self.logger.info("[BUY SKIP] market=KR symbol=%s name=%r reason=ORDER_LOCKED", symbol, name)
            self._write_skip_event("KR", symbol, name, "ORDER_LOCKED", snapshot=snapshot)
            return
        signal = self.entry_signal.evaluate("KR", snapshot, self._position_state(), self._risk_state(), self.risk_manager)
        self.logger.info("[BUY CHECK] market=domestic symbol=%s name=%r signal=%s", symbol, name, signal)
        self._write_strategy_decision("BUY", "KR", symbol, name, signal, snapshot)
        if not signal.allowed:
            return
        if is_new_buy_blocked:
            self.logger.info("[BUY SKIP] market=domestic symbol=%s name=%r reason=NEW_BUY_TIME_BLOCKED", symbol, name)
            self._write_skip_event("KR", symbol, name, "NEW_BUY_TIME_BLOCKED", snapshot=snapshot)
            return
        available_buy_quantity = self._call_with_retries(
            lambda: self.domestic_account.get_available_buy_quantity(symbol),
            "available_buy_quantity",
            symbol,
        )
        quantity = calculate_order_quantity(available_buy_quantity, self.settings.force_quantity)
        if quantity < 1:
            self.logger.info(
                "[BUY SKIP] market=domestic symbol=%s name=%r reason=NO_ORDER_QUANTITY available_buy_quantity=%s",
                symbol,
                name,
                available_buy_quantity,
            )
            self._write_skip_event(
                "KR",
                symbol,
                name,
                "NO_ORDER_QUANTITY",
                {"available_buy_quantity": available_buy_quantity},
                snapshot,
            )
            return
        self._place_domestic_buy(symbol, quantity, snapshot.current_price)

    def _handle_domestic_sell(self, position: Position, snapshot) -> None:
        if position.quantity <= 0:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=NO_HELD_QUANTITY", position.symbol)
            self._write_skip_event("KR", position.symbol, self._get_symbol_name("KR", position.symbol), "NO_HELD_QUANTITY", snapshot=snapshot)
            return
        if position.symbol in self.state.pending_sell_symbols:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=PENDING_SELL_ORDER_EXISTS", position.symbol)
            self._write_skip_event("KR", position.symbol, self._get_symbol_name("KR", position.symbol), "PENDING_SELL_ORDER_EXISTS", snapshot=snapshot)
            return
        if position.symbol in self.state.order_locked_symbols:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=ORDER_LOCKED", position.symbol)
            self._write_skip_event("KR", position.symbol, self._get_symbol_name("KR", position.symbol), "ORDER_LOCKED", snapshot=snapshot)
            return
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
        self.order_execution_service.place_buy(self.state, symbol, quantity, price)

    def _place_domestic_exit(self, symbol: str, quantity: int, reason: str) -> None:
        self.order_execution_service.place_exit(self.state, symbol, quantity, reason)

    def _build_domestic_snapshot(self, symbol: str):
        rows = self._call_with_retries(lambda: self.domestic_market.get_minute_chart(symbol), "minute_chart", symbol)
        candles = parse_domestic_candles(rows)
        price = self._call_with_retries(lambda: self.domestic_market.get_current_price(symbol), "current_price", symbol)
        orderbook = self._call_with_retries(lambda: self.domestic_market.get_orderbook(symbol), "orderbook", symbol)
        return self.snapshot_builder.build(symbol, candles, price, float(orderbook["spread_rate"]))

    def _get_domestic_cycle_symbols(self) -> list[str]:
        symbols = list(dict.fromkeys(self.watchlist_manager.get_symbols("KR") + list(self.state.positions)))
        return symbols

    def _sync_domestic_positions(self) -> bool:
        return self.account_service.sync_positions(self.state)

    def _position_state(self) -> PositionState:
        return PositionState(positions=tuple(self.state.positions.values()))

    def _risk_state(self) -> RiskState:
        return RiskState(
            current_position_count=len(self.state.positions),
            daily_loss_rate=0.0,
            daily_loss_amount=self.state.daily_loss_amount,
            consecutive_loss_count=self.state.consecutive_loss_count,
            safe_mode=self.state.safe_mode,
            kill_switch_active=self._is_kill_switch_active(),
            daily_entry_count_by_symbol=dict(self.state.daily_entry_count_by_symbol),
            pending_order_symbols=set(self.state.pending_order_symbols),
            order_locked_symbols=set(self.state.order_locked_symbols),
            held_symbols=set(self.state.positions.keys()),
        )

    def _recover_startup_state(self) -> None:
        self.recover_once()

    def _restore_open_orders(self, rows: list[dict[str, Any]]) -> None:
        self.account_service.restore_open_orders(rows, self.state)

    def _restore_daily_execution_state(self, rows: list[dict[str, Any]]) -> None:
        self.account_service.restore_daily_execution_state(rows, self.state)

    def _sync_domestic_executions(self) -> None:
        self.account_service.sync_executions(self.state)

    def _persist_execution_rows(self, rows: list[dict[str, Any]]) -> None:
        self.account_service.persist_execution_rows(rows)

    def _persist_position_rows(self, rows: list[dict[str, Any]]) -> None:
        self.account_service.persist_position_rows(rows, self.state)

    def _save_account_snapshot(self, force: bool = False) -> None:
        self.account_service.save_account_snapshot(self.state, force)

    def _reconcile_uncertain_order(self, symbol: str, side: str, exc: Exception) -> bool:
        return self.account_service.reconcile_uncertain_order(
            symbol,
            side,
            exc,
            self._get_symbol_name("KR", symbol),
        )

    def _call_with_retries(self, callback: Callable[[], Any], operation: str, symbol: str | None = None, max_attempts: int = 2) -> Any:
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                return callback()
            except Exception as exc:
                last_error = exc
                self.logger.warning("[API RETRY] operation=%s symbol=%s attempt=%s error=%s", operation, symbol, attempt, exc)
                write_trade_event(
                    "api_call_failed",
                    {
                        **self._event_context("KR", symbol),
                        "operation": operation,
                        "attempt": attempt,
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                )
        self._activate_safe_mode("API_CONSECUTIVE_FAILURE", {"operation": operation, "symbol": symbol})
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"API operation failed: {operation}")

    def _activate_safe_mode(self, reason: str, extra: dict | None = None) -> None:
        self.state.safe_mode = True
        self.state.kill_switch_reasons.add(reason)
        self.logger.error("[SAFE MODE] reason=%s", reason)
        write_trade_event(
            "safe_mode_activated",
            {
                **self._event_context("KR"),
                "reason": reason,
                "kill_switch_reasons": sorted(self.state.kill_switch_reasons),
                "extra": extra or {},
            },
        )

    def _activate_kill_switch(self, reason: str) -> None:
        self.state.safe_mode = True
        self.state.kill_switch_reasons.add(reason)
        self.logger.error("[KILL SWITCH] reason=%s", reason)
        write_trade_event(
            "kill_switch_activated",
            {
                **self._event_context("KR"),
                "reason": reason,
                "kill_switch_reasons": sorted(self.state.kill_switch_reasons),
            },
        )

    def _is_kill_switch_active(self) -> bool:
        return bool(self.state.kill_switch_reasons)

    def _write_strategy_decision(self, side: str, market: str, symbol: str, name: str | None, signal, snapshot) -> None:
        write_trade_event(
            "strategy_decision",
            {
                **self._event_context(market, symbol, name),
                "side": side,
                "strategy_name": self.strategy_metadata["strategy_name"],
                "strategy_version": self.strategy_metadata["strategy_version"],
                "applied_config": self.strategy_metadata["applied_config"],
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
            "daily_realized_pnl": self.state.daily_realized_pnl,
            "daily_loss_limit": self.settings.daily_max_loss_amount,
            "daily_loss_rate_limit": self.settings.daily_max_loss_rate,
            "daily_loss_limit_enabled": self.bot_config.risk.enforce_daily_loss_limit,
            "daily_loss_amount": self.state.daily_loss_amount,
            "consecutive_losses": self.state.consecutive_loss_count,
            "max_positions": self.settings.max_position_count,
            "current_positions_count": len(self.state.positions),
            "held_symbols": sorted(self.state.positions),
            "pending_order_symbols": sorted(self.state.pending_order_symbols),
            "pending_buy_symbols": sorted(self.state.pending_buy_symbols),
            "pending_sell_symbols": sorted(self.state.pending_sell_symbols),
            "order_locked_symbols": sorted(self.state.order_locked_symbols),
            "daily_entry_count_by_symbol": dict(self.state.daily_entry_count_by_symbol),
            "safe_mode": self.state.safe_mode,
            "kill_switch_status": "on" if self._is_kill_switch_active() else "off",
            "risk_block_reason": sorted(self.state.kill_switch_reasons),
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
        return self.order_execution_service.get_exit_quantity(self.state, symbol, quantity, reason)

    def _update_position_after_exit(self, symbol: str, sell_quantity: int, reason: str) -> None:
        self.order_execution_service.update_position_after_exit(
            self.state,
            symbol,
            sell_quantity,
            reason,
        )

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
        if _parse_hhmm(start, now) <= now <= _parse_hhmm(end, now):
            return True
    return False


def _rate_gap(current_price: int | float, base_price: int | float) -> float | None:
    if base_price <= 0:
        return None
    return ((current_price - base_price) / base_price) * 100


def _safe_ratio(value: int | float, base_value: int | float) -> float | None:
    if base_value <= 0:
        return None
    return value / base_value
