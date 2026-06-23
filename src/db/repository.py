import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db.connection import get_connection
from src.db.schema import initialize_database
from src.logs.trade_logger import get_trade_logger


class TradingRepository:
    def __init__(self, db_path: str | Path | None = None):
        """Create a trading repository and initialize SQLite schema.

        @param db_path: Optional SQLite database path.
        """
        self.db_path = db_path
        self.logger = get_trade_logger()
        self._initialize()

    def insert_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str,
        status: str = "REQUESTED",
        order_id: str | None = None,
        symbol_name: str | None = None,
        price: float | None = None,
        reason: str | None = None,
        strategy_name: str | None = None,
        raw_json: Any = None,
        created_at: datetime | None = None,
    ) -> int | None:
        """Insert one order request row.

        @param symbol: Six-digit domestic stock code.
        @param side: BUY or SELL.
        @param quantity: Requested quantity.
        @param order_type: Order type such as MARKET.
        @param status: Initial order status.
        @param order_id: Broker order id when already available.
        @param symbol_name: Optional stock name.
        @param price: Requested price, or None for market order.
        @param reason: Optional status reason.
        @param strategy_name: Optional strategy name.
        @param raw_json: Raw request/response payload.
        @param created_at: Optional save timestamp.
        @returns: Inserted row id, or None when DB save failed.
        """
        saved_at = created_at or datetime.now()
        inserted_id = self._execute_insert(
            """
            INSERT INTO orders (
              created_at,
              trade_date,
              order_id,
              symbol,
              symbol_name,
              side,
              quantity,
              price,
              order_type,
              status,
              reason,
              strategy_name,
              raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _datetime_text(saved_at),
                _trade_date_text(saved_at),
                order_id,
                symbol,
                symbol_name,
                side,
                quantity,
                price,
                order_type,
                status,
                reason,
                strategy_name,
                _json_text(raw_json),
            ),
            "insert_order",
        )
        return inserted_id

    def update_order_status(
        self,
        *,
        status: str,
        order_row_id: int | None = None,
        order_id: str | None = None,
        reason: str | None = None,
        raw_json: Any = None,
    ) -> bool:
        """Update an order status by local row id or broker order id.

        @param status: New order status.
        @param order_row_id: Local orders.id value.
        @param order_id: Broker order id.
        @param reason: Optional status reason.
        @param raw_json: Raw response payload.
        @returns: True when the update statement ran successfully.
        """
        if order_row_id is None and not order_id:
            self.logger.error("[DB SAVE FAILED] operation=update_order_status error=missing_order_identifier")
            return False
        if order_row_id is not None:
            return self._execute(
                """
                UPDATE orders
                SET status = ?,
                    order_id = COALESCE(?, order_id),
                    reason = ?,
                    raw_json = COALESCE(?, raw_json)
                WHERE id = ?
                """,
                (status, order_id, reason, _json_text(raw_json), order_row_id),
                "update_order_status",
            )
        return self._execute(
            """
            UPDATE orders
            SET status = ?,
                reason = ?,
                raw_json = COALESCE(?, raw_json)
            WHERE order_id = ?
            """,
            (status, reason, _json_text(raw_json), order_id),
            "update_order_status",
        )

    def insert_execution(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_id: str | None = None,
        symbol_name: str | None = None,
        fee: float = 0,
        tax: float = 0,
        gross_pnl: float | None = None,
        total_cost: float = 0,
        realized_pnl: float | None = None,
        realized_pnl_rate: float | None = None,
        strategy_name: str | None = None,
        raw_json: Any = None,
        created_at: datetime | None = None,
    ) -> int | None:
        """Insert one execution row and ignore duplicate rows.

        @param symbol: Six-digit domestic stock code.
        @param side: BUY or SELL.
        @param quantity: Executed quantity.
        @param price: Executed price.
        @param order_id: Broker order id.
        @param symbol_name: Optional stock name.
        @param fee: Execution fee.
        @param tax: Execution tax.
        @param gross_pnl: Gross realized profit/loss before costs.
        @param total_cost: Total buy/sell fees and sell tax.
        @param realized_pnl: Realized profit/loss.
        @param realized_pnl_rate: Realized profit/loss rate.
        @param strategy_name: Optional strategy name.
        @param raw_json: Raw execution payload.
        @param created_at: Optional execution timestamp.
        @returns: Inserted row id, or None when ignored or failed.
        """
        saved_at = created_at or datetime.now()
        inserted_id = self._execute_insert(
            """
            INSERT OR IGNORE INTO executions (
              created_at,
              trade_date,
              order_id,
              symbol,
              symbol_name,
              side,
              quantity,
              price,
              fee,
              tax,
              gross_pnl,
              total_cost,
              realized_pnl,
              realized_pnl_rate,
              strategy_name,
              raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _datetime_text(saved_at),
                _trade_date_text(saved_at),
                order_id,
                symbol,
                symbol_name,
                side,
                quantity,
                price,
                fee,
                tax,
                gross_pnl,
                total_cost,
                realized_pnl,
                realized_pnl_rate,
                strategy_name,
                _json_text(raw_json),
            ),
            "insert_execution",
        )
        self.update_execution_financials(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
            tax=tax,
            gross_pnl=gross_pnl,
            total_cost=total_cost,
            realized_pnl=realized_pnl,
            realized_pnl_rate=realized_pnl_rate,
        )
        return inserted_id

    def update_execution_financials(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        fee: float,
        tax: float,
        gross_pnl: float | None,
        total_cost: float,
        realized_pnl: float | None,
        realized_pnl_rate: float | None,
        order_id: str | None = None,
    ) -> bool:
        """Update cost and realized profit fields for one execution.

        @param symbol: Six-digit domestic stock code.
        @param side: BUY or SELL.
        @param quantity: Executed quantity.
        @param price: Executed price.
        @param fee: Execution fee.
        @param tax: Execution tax.
        @param gross_pnl: Gross realized profit/loss before costs.
        @param total_cost: Total allocated transaction costs.
        @param realized_pnl: Net realized profit/loss.
        @param realized_pnl_rate: Net realized return rate.
        @param order_id: Broker order id when available.
        @returns: True when the update statement ran successfully.
        """
        if order_id:
            where_sql = "order_id = ?"
            where_params = (order_id,)
        else:
            where_sql = "symbol = ? AND side = ? AND quantity = ? AND price = ?"
            where_params = (symbol, side, quantity, price)
        return self._execute(
            f"""
            UPDATE executions
            SET fee = ?,
                tax = ?,
                gross_pnl = ?,
                total_cost = ?,
                realized_pnl = ?,
                realized_pnl_rate = ?
            WHERE {where_sql}
            """,
            (
                fee,
                tax,
                gross_pnl,
                total_cost,
                realized_pnl,
                realized_pnl_rate,
                *where_params,
            ),
            "update_execution_financials",
        )

    def get_executions(self, trade_date: str) -> list[dict[str, Any]]:
        """Return executions saved for one trade date.

        @param trade_date: Date in YYYY-MM-DD format.
        @returns: Execution rows ordered by creation time.
        """
        try:
            with get_connection(self.db_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT * FROM executions WHERE trade_date = ? ORDER BY created_at, id",
                    (trade_date,),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error:
            self.logger.exception("[DB READ FAILED] operation=get_executions")
            return []

    def get_orders(self, trade_date: str) -> list[dict[str, Any]]:
        """Return orders saved for one trade date.

        @param trade_date: Date in YYYY-MM-DD format.
        @returns: Order rows ordered by creation time.
        """
        return self._fetch_all(
            "SELECT * FROM orders WHERE trade_date = ? ORDER BY created_at, id",
            (trade_date,),
            "get_orders",
        )

    def get_current_positions(self) -> list[dict[str, Any]]:
        """Return the current positive-quantity position cache.

        @returns: Current position rows ordered by symbol.
        """
        return self._fetch_all(
            "SELECT * FROM positions WHERE quantity > 0 ORDER BY symbol",
            (),
            "get_current_positions",
        )

    def get_bot_events(self, trade_date: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Return bot events saved for one trade date.

        @param trade_date: Date in YYYY-MM-DD format.
        @param limit: Optional maximum number of newest events.
        @returns: Event rows ordered from oldest to newest.
        """
        if limit is not None and limit < 1:
            return []
        if limit is None:
            return self._fetch_all(
                "SELECT * FROM bot_events WHERE trade_date = ? ORDER BY event_time, id",
                (trade_date,),
                "get_bot_events",
            )
        rows = self._fetch_all(
            """
            SELECT *
            FROM bot_events
            WHERE trade_date = ?
            ORDER BY event_time DESC, id DESC
            LIMIT ?
            """,
            (trade_date, limit),
            "get_bot_events",
        )
        rows.reverse()
        return rows

    def insert_bot_event(self, event: dict[str, Any]) -> int | None:
        """Insert one structured bot event.

        @param event: Event generated by write_trade_event.
        @returns: Inserted row id, or None when DB save failed.
        """
        event_time = str(event.get("timestamp") or datetime.now().astimezone().isoformat(timespec="milliseconds"))
        decision = event.get("decision")
        decision_reason = decision.get("reason") if isinstance(decision, dict) else None
        quantity = _first_value(
            event,
            ("filled_quantity", "requested_quantity", "quantity"),
        )
        price = _first_value(
            event,
            ("filled_price", "decision_price", "requested_price", "price"),
        )
        reason = _first_value(
            event,
            ("reason", "fail_reason", "exit_reason", "entry_reason"),
        ) or decision_reason
        message = _first_value(
            event,
            ("message", "error", "fail_reason", "order_status"),
        )
        return self._execute_insert(
            """
            INSERT INTO bot_events (
              event_time,
              trade_date,
              event_type,
              market,
              symbol,
              symbol_name,
              side,
              quantity,
              price,
              reason,
              message,
              payload_json,
              created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_time,
                event_time[:10],
                str(event.get("event_type") or "unknown"),
                _optional_text(event.get("market")),
                _optional_text(event.get("symbol")),
                _optional_text(event.get("symbol_name")),
                _optional_text(event.get("side")),
                _optional_int(quantity),
                _optional_float(price),
                _optional_text(reason),
                _optional_text(message),
                _bot_event_json(event),
                _datetime_text(datetime.now()),
            ),
            "insert_bot_event",
        )

    def insert_account_snapshot(
        self,
        *,
        cash_balance: float | None,
        available_cash: float | None,
        stock_value: float | None,
        total_asset: float | None,
        unrealized_pnl: float | None,
        daily_realized_pnl: float | None,
        cumulative_cost: float | None,
        raw_json: Any = None,
        recorded_at: datetime | None = None,
    ) -> int | None:
        """Insert one account asset snapshot.

        @param cash_balance: Account deposit/cash balance.
        @param available_cash: Current market-buy available cash.
        @param stock_value: Current stock evaluation amount.
        @param total_asset: Current total evaluated asset.
        @param unrealized_pnl: Current unrealized profit/loss.
        @param daily_realized_pnl: Today's net realized profit/loss.
        @param cumulative_cost: Today's cumulative fees and taxes.
        @param raw_json: Raw KIS account summary.
        @param recorded_at: Optional snapshot timestamp.
        @returns: Inserted row id, or None when DB save failed.
        """
        saved_at = recorded_at or datetime.now()
        return self._execute_insert(
            """
            INSERT INTO account_snapshots (
              recorded_at,
              trade_date,
              cash_balance,
              available_cash,
              stock_value,
              total_asset,
              unrealized_pnl,
              daily_realized_pnl,
              cumulative_cost,
              raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _datetime_text(saved_at),
                _trade_date_text(saved_at),
                cash_balance,
                available_cash,
                stock_value,
                total_asset,
                unrealized_pnl,
                daily_realized_pnl,
                cumulative_cost,
                _json_text(raw_json),
            ),
            "insert_account_snapshot",
        )

    def get_cumulative_execution_cost(self, trade_date: str) -> float:
        """Return cumulative execution fees and taxes for one date.

        @param trade_date: Date in YYYY-MM-DD format.
        @returns: Sum of execution fees and taxes.
        """
        try:
            with get_connection(self.db_path) as connection:
                value = connection.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(fee, 0) + COALESCE(tax, 0)), 0)
                    FROM executions
                    WHERE trade_date = ?
                    """,
                    (trade_date,),
                ).fetchone()[0]
            return float(value or 0)
        except sqlite3.Error:
            self.logger.exception("[DB READ FAILED] operation=get_cumulative_execution_cost")
            return 0.0

    def get_latest_account_snapshot(self) -> dict[str, Any] | None:
        """Return the most recently saved account snapshot.

        @returns: Latest account snapshot row, or None when unavailable.
        """
        rows = self._fetch_all(
            "SELECT * FROM account_snapshots ORDER BY recorded_at DESC, id DESC LIMIT 1",
            (),
            "get_latest_account_snapshot",
        )
        return rows[0] if rows else None

    def upsert_position(
        self,
        *,
        symbol: str,
        quantity: int,
        symbol_name: str | None = None,
        avg_price: float | None = None,
        current_price: float | None = None,
        market_value: float | None = None,
        unrealized_pnl: float | None = None,
        unrealized_pnl_rate: float | None = None,
        strategy_name: str | None = None,
        source: str = "KIS_API",
        raw_json: Any = None,
        updated_at: datetime | None = None,
    ) -> bool:
        """Insert or update a current position cache row by symbol.

        @param symbol: Six-digit domestic stock code.
        @param quantity: Current held quantity.
        @param symbol_name: Optional stock name.
        @param avg_price: Average purchase price.
        @param current_price: Current market price.
        @param market_value: Current market value.
        @param unrealized_pnl: Unrealized profit/loss.
        @param unrealized_pnl_rate: Unrealized profit/loss rate.
        @param strategy_name: Optional strategy name.
        @param source: Source label.
        @param raw_json: Raw balance payload.
        @param updated_at: Optional update timestamp.
        @returns: True when the upsert statement ran successfully.
        """
        saved_at = updated_at or datetime.now()
        return self._execute(
            """
            INSERT INTO positions (
              updated_at,
              trade_date,
              symbol,
              symbol_name,
              quantity,
              avg_price,
              current_price,
              market_value,
              unrealized_pnl,
              unrealized_pnl_rate,
              strategy_name,
              source,
              raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
              updated_at = excluded.updated_at,
              trade_date = excluded.trade_date,
              symbol_name = excluded.symbol_name,
              quantity = excluded.quantity,
              avg_price = excluded.avg_price,
              current_price = excluded.current_price,
              market_value = excluded.market_value,
              unrealized_pnl = excluded.unrealized_pnl,
              unrealized_pnl_rate = excluded.unrealized_pnl_rate,
              strategy_name = excluded.strategy_name,
              source = excluded.source,
              raw_json = excluded.raw_json
            """,
            (
                _datetime_text(saved_at),
                _trade_date_text(saved_at),
                symbol,
                symbol_name,
                quantity,
                avg_price,
                current_price,
                market_value,
                unrealized_pnl,
                unrealized_pnl_rate,
                strategy_name,
                source,
                _json_text(raw_json),
            ),
            "upsert_position",
        )

    def delete_positions_except(self, symbols: set[str]) -> bool:
        """Delete cached positions that are absent from the latest broker balance.

        @param symbols: Symbols present in the latest successful balance response.
        @returns: True when the delete statement ran successfully.
        @mutate: Removes stale position cache rows.
        """
        if not symbols:
            return self._execute("DELETE FROM positions", (), "delete_positions_except")
        placeholders = ", ".join("?" for _ in symbols)
        return self._execute(
            f"DELETE FROM positions WHERE symbol NOT IN ({placeholders})",
            tuple(sorted(symbols)),
            "delete_positions_except",
        )

    def _initialize(self) -> None:
        try:
            initialize_database(self.db_path)
        except Exception:
            self.logger.exception("[DB INIT FAILED]")

    def _execute(self, sql: str, params: tuple[Any, ...], operation: str) -> bool:
        try:
            with get_connection(self.db_path) as connection:
                connection.execute(sql, params)
            return True
        except sqlite3.Error:
            self.logger.exception("[DB SAVE FAILED] operation=%s", operation)
            return False

    def _execute_insert(self, sql: str, params: tuple[Any, ...], operation: str) -> int | None:
        try:
            with get_connection(self.db_path) as connection:
                cursor = connection.execute(sql, params)
                return cursor.lastrowid if cursor.rowcount > 0 else None
        except sqlite3.Error:
            self.logger.exception("[DB SAVE FAILED] operation=%s", operation)
            return None

    def _fetch_all(self, sql: str, params: tuple[Any, ...], operation: str) -> list[dict[str, Any]]:
        try:
            with get_connection(self.db_path) as connection:
                rows = connection.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error:
            self.logger.exception("[DB READ FAILED] operation=%s", operation)
            return []


def _datetime_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _trade_date_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _bot_event_json(event: dict[str, Any]) -> str:
    payload = dict(event)
    market_snapshot = payload.get("market_snapshot")
    if isinstance(market_snapshot, dict):
        summarized_snapshot = dict(market_snapshot)
        candles = summarized_snapshot.pop("candles", None)
        if isinstance(candles, list):
            summarized_snapshot["candle_count"] = len(candles)
        payload["market_snapshot"] = summarized_snapshot
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def _optional_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
