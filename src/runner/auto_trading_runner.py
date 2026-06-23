import time
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable, Dict

from src.broker.kis_account import KisAccount
from src.broker.kis_client import KisApiError
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.config.bot_config import BotConfig, TradingCostConfig
from src.config.env import Settings
from src.db.repository import TradingRepository
from src.domain.position import Position, PositionState
from src.logs.trade_logger import get_trade_logger, write_trade_event
from src.risk.risk_manager import RiskManager, RiskState
from src.risk.trading_cost import calculate_trade_cost_result
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
    pending_buy_symbols: set[str] = field(default_factory=set)
    pending_sell_symbols: set[str] = field(default_factory=set)
    order_locked_symbols: set[str] = field(default_factory=set)
    partial_profit_taken_symbols: set[str] = field(default_factory=set)
    last_exit_at_by_symbol: Dict[str, datetime] = field(default_factory=dict)
    daily_loss_amount: int = 0
    consecutive_loss_count: int = 0
    daily_realized_pnl: int = 0
    safe_mode: bool = False
    kill_switch_reasons: set[str] = field(default_factory=set)
    startup_recovered: bool = False


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
        trade_repository: TradingRepository | None = None,
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
        self.last_account_snapshot_at: datetime | None = None

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
            self._recover_startup_state()
        if self.bot_config.korea.enabled:
            if self.market_hours.is_domestic_open():
                self._run_domestic_cycle()
            else:
                self.logger.info("[AUTO WAIT] market=domestic")

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
            except Exception:
                self.logger.exception("[AUTO DOMESTIC CYCLE FAILED] symbol=%s", symbol)

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
        if symbol in self.state.order_locked_symbols:
            self.logger.info("[BUY SKIP] market=KR symbol=%s reason=ORDER_LOCKED", symbol)
            self._write_skip_event("KR", symbol, self._get_symbol_name("KR", symbol), "ORDER_LOCKED")
            return
        self.state.order_locked_symbols.add(symbol)
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
            self._save_account_snapshot(force=True)
        except Exception as exc:
            if isinstance(exc, KisApiError) and exc.is_definitive_rejection:
                self.logger.warning("[BUY ORDER REJECTED] market=KR symbol=%s quantity=%s error=%s", symbol, quantity, exc)
            else:
                self.logger.exception("[BUY ORDER UNCERTAIN] market=KR symbol=%s quantity=%s", symbol, quantity)
                if not self._reconcile_uncertain_order(symbol, "BUY", exc):
                    self._activate_safe_mode("BUY_ORDER_STATUS_UNCERTAIN")
        finally:
            self.state.pending_order_symbols.discard(symbol)
            self.state.order_locked_symbols.discard(symbol)

    def _place_domestic_exit(self, symbol: str, quantity: int, reason: str) -> None:
        sell_quantity = self._exit_quantity(symbol, quantity, reason)
        if sell_quantity < 1:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=NO_SELL_QUANTITY", symbol)
            self._write_skip_event("KR", symbol, self._get_symbol_name("KR", symbol), "NO_SELL_QUANTITY")
            return
        if symbol in self.state.order_locked_symbols:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=ORDER_LOCKED", symbol)
            self._write_skip_event("KR", symbol, self._get_symbol_name("KR", symbol), "ORDER_LOCKED")
            return
        self.state.order_locked_symbols.add(symbol)
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
            self._save_account_snapshot(force=True)
        except Exception as exc:
            if isinstance(exc, KisApiError) and exc.is_definitive_rejection:
                self.logger.warning("[SELL ORDER REJECTED] market=KR symbol=%s quantity=%s error=%s", symbol, sell_quantity, exc)
            else:
                self.logger.exception("[SELL ORDER UNCERTAIN] market=KR symbol=%s quantity=%s", symbol, sell_quantity)
                if not self._reconcile_uncertain_order(symbol, "SELL", exc):
                    self._activate_safe_mode("SELL_ORDER_STATUS_UNCERTAIN")
        finally:
            self.state.pending_order_symbols.discard(symbol)
            self.state.order_locked_symbols.discard(symbol)

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
        try:
            rows = self._call_with_retries(self.domestic_account.get_balance, "balance", "KR")
        except Exception:
            self._activate_safe_mode("BALANCE_SYNC_FAILED")
            return False
        account_positions = _create_positions_from_balance(rows)
        self.state.positions = account_positions
        self._persist_position_rows(rows)
        return True

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
        try:
            balance_rows = self._call_with_retries(self.domestic_account.get_balance, "startup_balance", "KR")
            self.state.positions = _create_positions_from_balance(balance_rows)
            self._persist_position_rows(balance_rows)
            open_orders = self._call_with_retries(self.domestic_account.get_open_orders, "startup_open_orders", "KR")
            self._restore_open_orders(open_orders)
            executions = self._call_with_retries(self.domestic_account.get_today_executions, "startup_today_executions", "KR")
            self._restore_daily_execution_state(executions)
            self._persist_execution_rows(executions)
            self.state.daily_realized_pnl = _calculate_daily_net_realized_pnl(executions, self.bot_config.cost)
            self.state.daily_loss_amount = abs(min(0, self.state.daily_realized_pnl))
            if (
                self.bot_config.risk.enforce_daily_loss_limit
                and self.state.daily_loss_amount >= self.settings.daily_max_loss_amount
            ):
                self._activate_kill_switch("DAILY_MAX_LOSS_AMOUNT_REACHED")
            self.state.startup_recovered = True
            write_trade_event(
                "startup_recovered",
                {
                    **self._event_context("KR"),
                    "positions": list(self.state.positions),
                    "pending_buy_symbols": sorted(self.state.pending_buy_symbols),
                    "pending_sell_symbols": sorted(self.state.pending_sell_symbols),
                    "daily_realized_pnl": self.state.daily_realized_pnl,
                    "daily_loss_amount": self.state.daily_loss_amount,
                    "consecutive_losses": self.state.consecutive_loss_count,
                    "safe_mode": self.state.safe_mode,
                    "kill_switch_reasons": sorted(self.state.kill_switch_reasons),
                },
            )
        except Exception as exc:
            self.state.startup_recovered = True
            self.logger.exception("[STARTUP RECOVERY FAILED]")
            self._activate_safe_mode("STARTUP_RECOVERY_FAILED", {"error": str(exc), "error_type": exc.__class__.__name__})

    def _restore_open_orders(self, rows: list[dict[str, Any]]) -> None:
        self.state.pending_order_symbols.clear()
        self.state.pending_buy_symbols.clear()
        self.state.pending_sell_symbols.clear()
        for row in rows:
            symbol = _row_symbol(row)
            if not symbol:
                continue
            side = _row_order_side(row)
            if side == "BUY":
                self.state.pending_buy_symbols.add(symbol)
                self.state.pending_order_symbols.add(symbol)
            elif side == "SELL":
                self.state.pending_sell_symbols.add(symbol)
                self.state.pending_order_symbols.add(symbol)

    def _restore_daily_execution_state(self, rows: list[dict[str, Any]]) -> None:
        self.state.daily_entry_count_by_symbol.clear()
        consecutive_losses = 0
        for row in rows:
            symbol = _row_symbol(row)
            side = _row_order_side(row)
            if symbol and side == "BUY":
                self.state.daily_entry_count_by_symbol[symbol] = self.state.daily_entry_count_by_symbol.get(symbol, 0) + 1
            profit_loss = _row_profit_loss(row)
            if profit_loss is None:
                continue
            if profit_loss < 0:
                consecutive_losses += 1
            elif profit_loss > 0:
                consecutive_losses = 0
        self.state.consecutive_loss_count = consecutive_losses
        if self.state.consecutive_loss_count >= 3:
            self._activate_kill_switch("MAX_CONSECUTIVE_LOSS_COUNT_REACHED")

    def _sync_domestic_executions(self) -> None:
        try:
            rows = self._call_with_retries(self.domestic_account.get_today_executions, "today_executions", "KR")
        except Exception:
            self._activate_safe_mode("EXECUTION_SYNC_FAILED")
            return
        self._restore_daily_execution_state(rows)
        self._persist_execution_rows(rows)

    def _persist_execution_rows(self, rows: list[dict[str, Any]]) -> None:
        if self.trade_repository is None:
            return
        for row, financials in _create_execution_financial_rows(rows, self.bot_config.cost):
            symbol = _row_symbol(row)
            side = _row_order_side(row)
            quantity = _row_execution_quantity(row)
            price = _row_execution_price(row)
            if not symbol or side is None or quantity < 1 or price is None:
                continue
            self.trade_repository.insert_execution(
                order_id=_row_order_id(row),
                symbol=symbol,
                symbol_name=_row_symbol_name(row),
                side=side,
                quantity=quantity,
                price=price,
                fee=financials["fee"],
                tax=financials["tax"],
                gross_pnl=financials["gross_pnl"],
                total_cost=financials["total_cost"],
                realized_pnl=financials["realized_pnl"],
                realized_pnl_rate=financials["realized_pnl_rate"],
                strategy_name=self.bot_config.strategy.name,
                raw_json=row,
                created_at=_row_created_at(row),
            )

    def _persist_position_rows(self, rows: list[dict[str, Any]]) -> None:
        if self.trade_repository is None:
            return
        for row in rows:
            symbol = _row_symbol(row)
            if not symbol:
                continue
            self.trade_repository.upsert_position(
                symbol=symbol,
                symbol_name=_row_symbol_name(row),
                quantity=_to_int(row.get("hldg_qty") or row.get("ord_psbl_qty") or 0),
                avg_price=_row_float(row, ("pchs_avg_pric", "avg_prvs", "avg_price")),
                current_price=_row_float(row, ("prpr", "now_pric", "stck_prpr", "current_price")),
                market_value=_row_float(row, ("evlu_amt", "market_value")),
                unrealized_pnl=_row_float(row, ("evlu_pfls_amt", "unrealized_pnl")),
                unrealized_pnl_rate=_row_float(row, ("evlu_pfls_rt", "unrealized_pnl_rate")),
                strategy_name=self.bot_config.strategy.name if symbol in self.state.positions else None,
                raw_json=row,
            )

    def _save_account_snapshot(self, force: bool = False) -> None:
        now = datetime.now()
        if not force and self.last_account_snapshot_at is not None:
            if now - self.last_account_snapshot_at < timedelta(minutes=5):
                return
        try:
            summary = self.domestic_account.get_account_summary()
            available_cash = self.domestic_account.get_available_cash()
            snapshot = {
                "cash_balance": _row_float(summary, ("dnca_tot_amt", "cash_balance")),
                "available_cash": float(available_cash),
                "stock_value": _row_float(summary, ("scts_evlu_amt", "stock_value")),
                "total_asset": _row_float(summary, ("tot_evlu_amt", "nass_amt", "total_asset")),
                "unrealized_pnl": _row_float(summary, ("evlu_pfls_smtl_amt", "unrealized_pnl")),
                "daily_realized_pnl": float(self.state.daily_realized_pnl),
                "cumulative_cost": (
                    self.trade_repository.get_cumulative_execution_cost(now.strftime("%Y-%m-%d"))
                    if self.trade_repository is not None
                    else 0.0
                ),
            }
        except Exception:
            self.logger.exception("[ACCOUNT SNAPSHOT FAILED]")
            return

        if self.trade_repository is not None:
            self.trade_repository.insert_account_snapshot(
                **snapshot,
                raw_json=summary,
                recorded_at=now,
            )
        self.last_account_snapshot_at = now
        self.logger.info(
            "[ACCOUNT SNAPSHOT] total_asset=%s cash_balance=%s available_cash=%s stock_value=%s unrealized_pnl=%s daily_realized_pnl=%s cumulative_cost=%s",
            snapshot["total_asset"],
            snapshot["cash_balance"],
            snapshot["available_cash"],
            snapshot["stock_value"],
            snapshot["unrealized_pnl"],
            snapshot["daily_realized_pnl"],
            snapshot["cumulative_cost"],
        )
        write_trade_event(
            "account_snapshot",
            {
                **self._event_context("KR"),
                **snapshot,
            },
        )

    def _reconcile_uncertain_order(self, symbol: str, side: str, exc: Exception) -> bool:
        try:
            open_orders = self._call_with_retries(self.domestic_account.get_open_orders, "reconcile_open_orders", symbol)
            executions = self._call_with_retries(self.domestic_account.get_today_executions, "reconcile_today_executions", symbol)
        except Exception as reconcile_exc:
            write_trade_event(
                "order_reconcile_failed",
                {
                    **self._event_context("KR", symbol, self._get_symbol_name("KR", symbol)),
                    "side": side,
                    "original_error": str(exc),
                    "reconcile_error": str(reconcile_exc),
                },
            )
            return False
        has_open_order = any(_row_symbol(row) == symbol and _row_order_side(row) == side for row in open_orders)
        has_execution = any(_row_symbol(row) == symbol and _row_order_side(row) == side for row in executions)
        write_trade_event(
            "order_reconciled",
            {
                **self._event_context("KR", symbol, self._get_symbol_name("KR", symbol)),
                "side": side,
                "original_error": str(exc),
                "has_open_order": has_open_order,
                "has_execution": has_execution,
            },
        )
        return has_open_order or has_execution

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
            "buy_fee_percent": self.bot_config.cost.buy_fee_percent,
            "sell_fee_percent": self.bot_config.cost.sell_fee_percent,
            "sell_tax_percent": self.bot_config.cost.sell_tax_percent,
            "slippage_percent": self.bot_config.cost.slippage_percent,
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
        if _parse_hhmm(start, now) <= now <= _parse_hhmm(end, now):
            return True
    return False


def _to_int(value) -> int:
    if value in (None, ""):
        return 0
    return int(float(str(value).replace(",", "")))


def _create_positions_from_balance(rows: list[dict[str, Any]]) -> Dict[str, Position]:
    positions = {}
    for row in rows:
        symbol = _row_symbol(row)
        quantity = _to_int(row.get("hldg_qty") or row.get("ord_psbl_qty") or 0)
        average_price = _to_int(row.get("pchs_avg_pric") or row.get("avg_prvs") or 0)
        if symbol and quantity > 0 and average_price > 0:
            positions[symbol] = Position(symbol, quantity, average_price, datetime.now())
    return positions


def _row_symbol(row: dict[str, Any]) -> str:
    value = row.get("pdno") or row.get("prdt_code") or row.get("stck_shrn_iscd") or row.get("symbol") or ""
    return str(value).zfill(6) if value not in (None, "") else ""


def _row_order_side(row: dict[str, Any]) -> str | None:
    value = row.get("sll_buy_dvsn_cd") or row.get("sll_buy_dvsn_name") or row.get("side") or row.get("ord_dvsn_name")
    text = str(value or "").upper()
    if text in {"02", "BUY"} or "매수" in text:
        return "BUY"
    if text in {"01", "SELL"} or "매도" in text:
        return "SELL"
    return None


def _row_profit_loss(row: dict[str, Any]) -> int | None:
    for key in ("rlzt_pfls", "realized_pnl", "trad_pfls", "evlu_pfls_amt"):
        value = row.get(key)
        if value not in (None, ""):
            return _to_int(value)
    return None


def _row_symbol_name(row: dict[str, Any]) -> str | None:
    value = row.get("prdt_name") or row.get("prdt_name120") or row.get("hts_kor_isnm") or row.get("symbol_name")
    return str(value) if value not in (None, "") else None


def _row_order_id(row: dict[str, Any]) -> str | None:
    value = row.get("odno") or row.get("ODNO") or row.get("orgn_odno") or row.get("order_id")
    return str(value) if value not in (None, "") else None


def _row_execution_quantity(row: dict[str, Any]) -> int:
    return _to_int(row.get("tot_ccld_qty") or row.get("ccld_qty") or row.get("ord_qty") or row.get("quantity") or 0)


def _row_execution_price(row: dict[str, Any]) -> float | None:
    return _row_float(row, ("avg_prvs", "ccld_unpr", "ord_unpr", "price"))


def _create_execution_financial_rows(
    rows: list[dict[str, Any]],
    cost_config: TradingCostConfig,
) -> list[tuple[dict[str, Any], dict[str, float | None]]]:
    ordered_rows = sorted(rows, key=_row_created_at)
    buy_lots: dict[str, list[list[float]]] = {}
    results = []

    for row in ordered_rows:
        symbol = _row_symbol(row)
        side = _row_order_side(row)
        quantity = _row_execution_quantity(row)
        price = _row_execution_price(row)
        if not symbol or side is None or quantity < 1 or price is None:
            results.append((row, _empty_execution_financials()))
            continue

        amount = price * quantity
        execution_fee_percent = cost_config.buy_fee_percent if side == "BUY" else cost_config.sell_fee_percent
        execution_fee = amount * (execution_fee_percent / 100)
        execution_tax = amount * (cost_config.sell_tax_percent / 100) if side == "SELL" else 0.0

        if side == "BUY":
            buy_lots.setdefault(symbol, []).append([float(quantity), float(price)])
            results.append(
                (
                    row,
                    {
                        "fee": execution_fee,
                        "tax": 0.0,
                        "gross_pnl": None,
                        "total_cost": execution_fee,
                        "realized_pnl": None,
                        "realized_pnl_rate": None,
                    },
                )
            )
            continue

        remaining_quantity = float(quantity)
        matched_quantity = 0.0
        matched_buy_amount = 0.0
        lots = buy_lots.setdefault(symbol, [])
        while remaining_quantity > 0 and lots:
            lot_quantity, lot_price = lots[0]
            used_quantity = min(remaining_quantity, lot_quantity)
            matched_quantity += used_quantity
            matched_buy_amount += used_quantity * lot_price
            remaining_quantity -= used_quantity
            lot_quantity -= used_quantity
            if lot_quantity <= 0:
                lots.pop(0)
            else:
                lots[0][0] = lot_quantity

        if matched_quantity <= 0 or remaining_quantity > 0:
            results.append(
                (
                    row,
                    {
                        "fee": execution_fee,
                        "tax": execution_tax,
                        "gross_pnl": None,
                        "total_cost": execution_fee + execution_tax,
                        "realized_pnl": None,
                        "realized_pnl_rate": None,
                    },
                )
            )
            continue

        average_buy_price = matched_buy_amount / matched_quantity
        trade_result = calculate_trade_cost_result(
            average_buy_price,
            price,
            matched_quantity,
            buy_fee_percent=cost_config.buy_fee_percent,
            sell_fee_percent=cost_config.sell_fee_percent,
            sell_tax_percent=cost_config.sell_tax_percent,
        )
        results.append(
            (
                row,
                {
                    "fee": trade_result.sell_fee,
                    "tax": trade_result.sell_tax,
                    "gross_pnl": trade_result.gross_profit_loss,
                    "total_cost": trade_result.total_cost,
                    "realized_pnl": trade_result.net_profit_loss,
                    "realized_pnl_rate": trade_result.net_return_rate,
                },
            )
        )

    return results


def _calculate_daily_net_realized_pnl(rows: list[dict[str, Any]], cost_config: TradingCostConfig) -> int:
    total = sum(
        float(financials["realized_pnl"] or 0)
        for _, financials in _create_execution_financial_rows(rows, cost_config)
    )
    return int(round(total))


def _empty_execution_financials() -> dict[str, float | None]:
    return {
        "fee": 0.0,
        "tax": 0.0,
        "gross_pnl": None,
        "total_cost": 0.0,
        "realized_pnl": None,
        "realized_pnl_rate": None,
    }


def _row_float(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return float(str(value).replace(",", ""))
    return None


def _row_created_at(row: dict[str, Any]) -> datetime:
    date_text = str(row.get("ord_dt") or row.get("trad_dt") or row.get("ccld_dt") or row.get("trade_date") or "")
    time_text = str(row.get("ord_tmd") or row.get("ccld_tmd") or row.get("stck_cntg_hour") or row.get("created_time") or "")
    parsed = _parse_row_datetime(date_text, time_text)
    return parsed if parsed is not None else datetime.now()


def _parse_row_datetime(date_text: str, time_text: str) -> datetime | None:
    digits_date = "".join(char for char in date_text if char.isdigit())
    digits_time = "".join(char for char in time_text if char.isdigit())
    if len(digits_date) != 8:
        return None
    if len(digits_time) < 6:
        digits_time = digits_time.ljust(6, "0")
    try:
        return datetime.strptime(f"{digits_date}{digits_time[:6]}", "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _rate_gap(current_price: int | float, base_price: int | float) -> float | None:
    if base_price <= 0:
        return None
    return ((current_price - base_price) / base_price) * 100


def _safe_ratio(value: int | float, base_value: int | float) -> float | None:
    if base_value <= 0:
        return None
    return value / base_value
