from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from src.broker.kis_account import KisAccount
from src.config.bot_config import BotConfig, TradingCostConfig
from src.config.env import Settings
from src.config.strategy_metadata import create_strategy_metadata
from src.db.repository import TradingRepository
from src.domain.position import Position
from src.logs.trade_logger import write_trade_event
from src.risk.trading_cost import calculate_trade_cost_result
from src.runner.auto_trading_state import AutoTradingState


@dataclass(frozen=True)
class OrderExecutionSummary:
    status: str
    filled_quantity: int
    average_price: float
    unfilled_quantity: int
    order_id: str | None = None
    executed_at: datetime | None = None


class TradingAccountService:
    def __init__(
        self,
        settings: Settings,
        bot_config: BotConfig,
        domestic_account: KisAccount,
        trade_repository: TradingRepository | None,
        call_with_retries: Callable[..., Any],
        activate_safe_mode: Callable[[str, dict | None], None],
        activate_kill_switch: Callable[[str], None],
        event_context: Callable[..., dict[str, Any]],
        logger,
    ):
        """Create account recovery, synchronization, and persistence service.

        @param settings: Runtime safety settings.
        @param bot_config: Bot strategy and risk configuration.
        @param domestic_account: KIS account API wrapper.
        @param trade_repository: Optional trading repository.
        @param call_with_retries: API retry callback.
        @param activate_safe_mode: Safe-mode activation callback.
        @param activate_kill_switch: Kill-switch activation callback.
        @param event_context: Structured event context callback.
        @param logger: Trade logger.
        """
        self.settings = settings
        self.bot_config = bot_config
        self.domestic_account = domestic_account
        self.trade_repository = trade_repository
        self.call_with_retries = call_with_retries
        self.activate_safe_mode = activate_safe_mode
        self.activate_kill_switch = activate_kill_switch
        self.event_context = event_context
        self.logger = logger
        self.strategy_metadata = create_strategy_metadata(bot_config)
        self.last_account_snapshot_at: datetime | None = None

    def recover_startup_state(self, state: AutoTradingState) -> None:
        """Restore positions, pending orders, executions, and risk state.

        @param state: Mutable automatic trading state.
        @mutate: Replaces recovered state fields.
        """
        try:
            balance_rows = self.call_with_retries(self.domestic_account.get_balance, "startup_balance", "KR")
            state.positions = _create_positions_from_balance(balance_rows)
            self.persist_position_rows(balance_rows, state)
            open_orders = self.call_with_retries(self.domestic_account.get_open_orders, "startup_open_orders", "KR")
            self.restore_open_orders(open_orders, state)
            executions = self.call_with_retries(
                self.domestic_account.get_today_executions,
                "startup_today_executions",
                "KR",
            )
            self.restore_daily_execution_state(executions, state)
            self.persist_execution_rows(executions)
            self.reconcile_order_states(open_orders, executions, state)
            state.daily_realized_pnl = _calculate_daily_net_realized_pnl(executions, self.bot_config.cost)
            state.daily_loss_amount = abs(min(0, state.daily_realized_pnl))
            if (
                self.bot_config.risk.enforce_daily_loss_limit
                and state.daily_loss_amount >= self.settings.daily_max_loss_amount
            ):
                self.activate_kill_switch("DAILY_MAX_LOSS_AMOUNT_REACHED")
            state.startup_recovered = True
            write_trade_event(
                "startup_recovered",
                {
                    **self.event_context("KR"),
                    "positions": list(state.positions),
                    "pending_buy_symbols": sorted(state.pending_buy_symbols),
                    "pending_sell_symbols": sorted(state.pending_sell_symbols),
                    "daily_realized_pnl": state.daily_realized_pnl,
                    "daily_loss_amount": state.daily_loss_amount,
                    "consecutive_losses": state.consecutive_loss_count,
                    "safe_mode": state.safe_mode,
                    "kill_switch_reasons": sorted(state.kill_switch_reasons),
                    **self.strategy_metadata,
                },
            )
        except Exception as exc:
            state.startup_recovered = True
            self.logger.exception("[STARTUP RECOVERY FAILED]")
            self.activate_safe_mode(
                "STARTUP_RECOVERY_FAILED",
                {"error": str(exc), "error_type": exc.__class__.__name__},
            )

    def sync_positions(self, state: AutoTradingState) -> bool:
        """Synchronize current positions from the broker balance.

        @param state: Mutable automatic trading state.
        @returns: True when synchronization succeeds.
        @mutate: Replaces current positions.
        """
        try:
            rows = self.call_with_retries(self.domestic_account.get_balance, "balance", "KR")
        except Exception:
            self.activate_safe_mode("BALANCE_SYNC_FAILED", None)
            return False
        state.positions = _create_positions_from_balance(rows)
        self.persist_position_rows(rows, state)
        return True

    def sync_executions(self, state: AutoTradingState) -> None:
        """Synchronize today's executions and derived risk state.

        @param state: Mutable automatic trading state.
        @mutate: Updates daily entries and consecutive losses.
        """
        try:
            open_orders = self.call_with_retries(self.domestic_account.get_open_orders, "open_orders", "KR")
            rows = self.call_with_retries(self.domestic_account.get_today_executions, "today_executions", "KR")
        except Exception:
            self.activate_safe_mode("EXECUTION_SYNC_FAILED", None)
            return
        self.restore_open_orders(open_orders, state)
        self.restore_daily_execution_state(rows, state)
        self.persist_execution_rows(rows)
        self.reconcile_order_states(open_orders, rows, state)

    def reconcile_order_states(
        self,
        open_orders: list[dict[str, Any]],
        executions: list[dict[str, Any]],
        state: AutoTradingState,
        now: datetime | None = None,
    ) -> None:
        """Reconcile local active orders with broker open orders and executions.

        @param open_orders: Current broker open-order rows.
        @param executions: Current broker execution rows.
        @param state: Mutable automatic trading state.
        @param now: Optional reconciliation timestamp.
        @mutate: Updates local order statuses and may activate safe mode.
        """
        if self.trade_repository is None:
            return
        current_time = now or datetime.now()
        active_orders = self.trade_repository.get_active_orders(current_time.strftime("%Y-%m-%d"))
        open_order_ids = {_row_order_id(row) for row in open_orders if _row_order_id(row)}
        execution_order_ids = {_row_order_id(row) for row in executions if _row_order_id(row)}

        for order in active_orders:
            order_row_id = int(order["id"])
            order_id = str(order.get("order_id") or "") or None
            symbol = str(order.get("symbol") or "")
            side = str(order.get("side") or "")
            matched_execution = (
                order_id in execution_order_ids
                if order_id is not None
                else _has_symbol_side(executions, symbol, side)
            )
            matched_open_order = (
                order_id in open_order_ids
                if order_id is not None
                else _has_symbol_side(open_orders, symbol, side)
            )
            order_age_seconds = _get_order_age_seconds(order, current_time)

            if matched_execution and not matched_open_order:
                self.trade_repository.update_order_status(
                    order_row_id=order_row_id,
                    order_id=order_id,
                    status="FILLED",
                    reason=None,
                )
                continue

            if matched_open_order and order_age_seconds < self.bot_config.risk.unfilled_order_timeout_seconds:
                self.trade_repository.update_order_status(
                    order_row_id=order_row_id,
                    order_id=order_id,
                    status="PARTIALLY_FILLED" if matched_execution else "OPEN",
                    reason=None,
                )
                continue

            if order_age_seconds < self.bot_config.risk.unfilled_order_timeout_seconds:
                continue

            status = "UNFILLED_TIMEOUT" if matched_open_order else "RECONCILIATION_REQUIRED"
            reason = (
                f"order_age_seconds={int(order_age_seconds)} "
                f"timeout_seconds={self.bot_config.risk.unfilled_order_timeout_seconds}"
            )
            self.trade_repository.update_order_status(
                order_row_id=order_row_id,
                order_id=order_id,
                status=status,
                reason=reason,
            )
            write_trade_event(
                "order_reconciliation_required",
                {
                    **self.event_context("KR", symbol),
                    "side": side,
                    "order_id": order_id,
                    "order_row_id": order_row_id,
                    "order_status": status,
                    "reason": reason,
                },
            )
            self.activate_safe_mode(
                status,
                {
                    "symbol": symbol,
                    "side": side,
                    "order_id": order_id,
                    "order_row_id": order_row_id,
                },
            )

    def save_account_snapshot(self, state: AutoTradingState, force: bool = False) -> None:
        """Save one periodic account asset snapshot.

        @param state: Current automatic trading state.
        @param force: Whether to ignore the five-minute interval.
        @mutate: Updates the last snapshot timestamp.
        """
        now = datetime.now()
        if not force and self.last_account_snapshot_at is not None:
            if now - self.last_account_snapshot_at < timedelta(minutes=5):
                return
        try:
            summary = self.domestic_account.get_account_summary()
            available_cash = self.domestic_account.get_available_cash()
            broker_daily_realized_pnl = float(self.domestic_account.get_daily_realized_pnl())
            realized_pnl_difference = float(state.daily_realized_pnl) - broker_daily_realized_pnl
            snapshot = {
                "cash_balance": _row_float(summary, ("dnca_tot_amt", "cash_balance")),
                "available_cash": float(available_cash),
                "stock_value": _row_float(summary, ("scts_evlu_amt", "stock_value")),
                "total_asset": _row_float(summary, ("tot_evlu_amt", "nass_amt", "total_asset")),
                "unrealized_pnl": _row_float(summary, ("evlu_pfls_smtl_amt", "unrealized_pnl")),
                "daily_realized_pnl": float(state.daily_realized_pnl),
                "broker_daily_realized_pnl": broker_daily_realized_pnl,
                "realized_pnl_difference": realized_pnl_difference,
                "realized_pnl_difference_tolerance": self.bot_config.cost.realized_pnl_difference_tolerance,
                "realized_pnl_difference_within_tolerance": abs(realized_pnl_difference) <= self.bot_config.cost.realized_pnl_difference_tolerance,
                "cumulative_cost": (
                    self.trade_repository.get_cumulative_execution_cost(now.strftime("%Y-%m-%d"))
                    if self.trade_repository is not None
                    else 0.0
                ),
            }
        except Exception as exc:
            self.logger.exception("[ACCOUNT SNAPSHOT FAILED]")
            write_trade_event(
                "account_snapshot_failed",
                {
                    **self.event_context("KR"),
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                },
            )
            return

        if self.trade_repository is not None:
            self.trade_repository.insert_account_snapshot(
                cash_balance=snapshot["cash_balance"],
                available_cash=snapshot["available_cash"],
                stock_value=snapshot["stock_value"],
                total_asset=snapshot["total_asset"],
                unrealized_pnl=snapshot["unrealized_pnl"],
                daily_realized_pnl=snapshot["daily_realized_pnl"],
                cumulative_cost=snapshot["cumulative_cost"],
                broker_daily_realized_pnl=snapshot["broker_daily_realized_pnl"],
                realized_pnl_difference=snapshot["realized_pnl_difference"],
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
        write_trade_event("account_snapshot", {**self.event_context("KR"), **snapshot})
        if not snapshot["realized_pnl_difference_within_tolerance"]:
            write_trade_event(
                "realized_pnl_difference",
                {
                    **self.event_context("KR"),
                    "internal_daily_realized_pnl": snapshot["daily_realized_pnl"],
                    "broker_daily_realized_pnl": snapshot["broker_daily_realized_pnl"],
                    "difference": snapshot["realized_pnl_difference"],
                    "tolerance": snapshot["realized_pnl_difference_tolerance"],
                    **self.strategy_metadata,
                },
            )

    def get_order_execution_summary(
        self,
        order_response: dict[str, Any],
        symbol: str,
        side: str,
        requested_quantity: int,
        fallback_price: int | float = 0,
    ) -> OrderExecutionSummary:
        """Return actual execution quantity and price for a submitted order.

        @param order_response: Broker order response.
        @param symbol: Domestic stock code.
        @param side: BUY or SELL.
        @param requested_quantity: Requested order quantity.
        @param fallback_price: Dry-run fallback fill price.
        @returns: Execution summary.
        """
        order_id = _response_order_id(order_response)
        if self.settings.dry_run:
            return OrderExecutionSummary(
                status="FILLED",
                filled_quantity=requested_quantity,
                average_price=float(fallback_price),
                unfilled_quantity=0,
                order_id=order_id,
                executed_at=datetime.now(),
            )
        try:
            rows = self.call_with_retries(self.domestic_account.get_today_executions, "confirm_order_execution", symbol)
            open_orders = self.call_with_retries(self.domestic_account.get_open_orders, "confirm_open_order", symbol)
        except Exception:
            self.logger.exception("[ORDER EXECUTION CONFIRM FAILED] symbol=%s side=%s order_id=%s", symbol, side, order_id)
            return OrderExecutionSummary("UNCERTAIN", 0, 0.0, requested_quantity, order_id)

        matched_rows = [
            row
            for row in rows
            if _row_symbol(row) == symbol
            and _row_order_side(row) == side
            and (order_id is None or _row_order_id(row) in {None, order_id})
        ]
        filled_quantity = sum(_row_execution_quantity(row) for row in matched_rows)
        average_price = _weighted_average_execution_price(matched_rows)
        unfilled_quantity = max(0, requested_quantity - filled_quantity)
        has_open_order = any(
            _row_symbol(row) == symbol
            and _row_order_side(row) == side
            and (order_id is None or _row_order_id(row) in {None, order_id})
            for row in open_orders
        )
        status = _execution_status(filled_quantity, requested_quantity, has_open_order)
        if status in {"FILLED", "PARTIALLY_FILLED"} and self.trade_repository is not None:
            self.persist_execution_rows(matched_rows)
        return OrderExecutionSummary(
            status=status,
            filled_quantity=min(filled_quantity, requested_quantity),
            average_price=average_price or 0.0,
            unfilled_quantity=unfilled_quantity,
            order_id=order_id,
            executed_at=max((_row_created_at(row) for row in matched_rows), default=datetime.now()),
        )

    def reconcile_uncertain_order(
        self,
        symbol: str,
        side: str,
        exc: Exception,
        symbol_name: str | None,
    ) -> bool:
        """Check open orders and executions after an uncertain order result.

        @param symbol: Domestic stock code.
        @param side: BUY or SELL.
        @param exc: Original order exception.
        @param symbol_name: Optional stock name.
        @returns: True when an open order or execution is found.
        """
        try:
            open_orders = self.call_with_retries(
                self.domestic_account.get_open_orders,
                "reconcile_open_orders",
                symbol,
            )
            executions = self.call_with_retries(
                self.domestic_account.get_today_executions,
                "reconcile_today_executions",
                symbol,
            )
        except Exception as reconcile_exc:
            write_trade_event(
                "order_reconcile_failed",
                {
                    **self.event_context("KR", symbol, symbol_name),
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
                **self.event_context("KR", symbol, symbol_name),
                "side": side,
                "original_error": str(exc),
                "has_open_order": has_open_order,
                "has_execution": has_execution,
            },
        )
        return has_open_order or has_execution

    def restore_open_orders(self, rows: list[dict[str, Any]], state: AutoTradingState) -> None:
        """Restore pending-order symbol sets.

        @param rows: Broker open-order rows.
        @param state: Mutable automatic trading state.
        @mutate: Replaces pending-order sets.
        """
        state.pending_order_symbols.clear()
        state.pending_buy_symbols.clear()
        state.pending_sell_symbols.clear()
        for row in rows:
            symbol = _row_symbol(row)
            if not symbol:
                continue
            side = _row_order_side(row)
            if side == "BUY":
                state.pending_buy_symbols.add(symbol)
                state.pending_order_symbols.add(symbol)
            elif side == "SELL":
                state.pending_sell_symbols.add(symbol)
                state.pending_order_symbols.add(symbol)

    def restore_daily_execution_state(self, rows: list[dict[str, Any]], state: AutoTradingState) -> None:
        """Restore daily entry counts and consecutive loss count.

        @param rows: Broker execution rows.
        @param state: Mutable automatic trading state.
        @mutate: Replaces daily execution-derived state.
        """
        state.daily_entry_count_by_symbol.clear()
        consecutive_losses = 0
        for row in rows:
            symbol = _row_symbol(row)
            side = _row_order_side(row)
            if symbol and side == "BUY":
                state.daily_entry_count_by_symbol[symbol] = state.daily_entry_count_by_symbol.get(symbol, 0) + 1
            profit_loss = _row_profit_loss(row)
            if profit_loss is None:
                continue
            if profit_loss < 0:
                consecutive_losses += 1
            elif profit_loss > 0:
                consecutive_losses = 0
        state.consecutive_loss_count = consecutive_losses
        if state.consecutive_loss_count >= 3:
            self.activate_kill_switch("MAX_CONSECUTIVE_LOSS_COUNT_REACHED")

    def persist_execution_rows(self, rows: list[dict[str, Any]]) -> None:
        """Persist broker execution rows.

        @param rows: Broker execution rows.
        """
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

    def persist_position_rows(self, rows: list[dict[str, Any]], state: AutoTradingState) -> None:
        """Persist the latest positive-quantity position cache.

        @param rows: Broker balance rows.
        @param state: Current automatic trading state.
        @mutate: Removes stale repository position rows.
        """
        if self.trade_repository is None:
            return
        active_symbols = set()
        for row in rows:
            symbol = _row_symbol(row)
            if not symbol:
                continue
            quantity = _to_int(row.get("hldg_qty") or row.get("ord_psbl_qty") or 0)
            if quantity < 1:
                continue
            active_symbols.add(symbol)
            self.trade_repository.upsert_position(
                symbol=symbol,
                symbol_name=_row_symbol_name(row),
                quantity=quantity,
                avg_price=_row_float(row, ("pchs_avg_pric", "avg_prvs", "avg_price")),
                current_price=_row_float(row, ("prpr", "now_pric", "stck_prpr", "current_price")),
                market_value=_row_float(row, ("evlu_amt", "market_value")),
                unrealized_pnl=_row_float(row, ("evlu_pfls_amt", "unrealized_pnl")),
                unrealized_pnl_rate=_row_float(row, ("evlu_pfls_rt", "unrealized_pnl_rate")),
                strategy_name=self.bot_config.strategy.name if symbol in state.positions else None,
                raw_json=row,
            )
        self.trade_repository.delete_positions_except(active_symbols)


def _to_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(float(str(value).replace(",", "")))


def _create_positions_from_balance(rows: list[dict[str, Any]]) -> dict[str, Position]:
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


def _response_order_id(response: dict[str, Any]) -> str | None:
    output = response.get("output")
    if not isinstance(output, dict):
        return None
    value = output.get("ODNO") or output.get("odno") or output.get("SOR_ODNO") or response.get("order_id")
    return str(value) if value not in (None, "") else None


def _weighted_average_execution_price(rows: list[dict[str, Any]]) -> float | None:
    total_quantity = 0
    total_amount = 0.0
    for row in rows:
        quantity = _row_execution_quantity(row)
        price = _row_execution_price(row)
        if quantity < 1 or price is None:
            continue
        total_quantity += quantity
        total_amount += quantity * price
    if total_quantity <= 0:
        return None
    return total_amount / total_quantity


def _execution_status(filled_quantity: int, requested_quantity: int, has_open_order: bool) -> str:
    if filled_quantity >= requested_quantity:
        return "FILLED"
    if filled_quantity > 0:
        return "PARTIALLY_FILLED" if has_open_order else "FILLED"
    if has_open_order:
        return "ACCEPTED"
    return "UNCERTAIN"


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


def _has_symbol_side(rows: list[dict[str, Any]], symbol: str, side: str) -> bool:
    return any(_row_symbol(row) == symbol and _row_order_side(row) == side for row in rows)


def _get_order_age_seconds(order: dict[str, Any], now: datetime) -> float:
    created_at = datetime.strptime(str(order["created_at"]), "%Y-%m-%d %H:%M:%S")
    return max(0.0, (now - created_at).total_seconds())
