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
        return self._execute_insert(
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
        @param realized_pnl: Realized profit/loss.
        @param realized_pnl_rate: Realized profit/loss rate.
        @param strategy_name: Optional strategy name.
        @param raw_json: Raw execution payload.
        @param created_at: Optional execution timestamp.
        @returns: Inserted row id, or None when ignored or failed.
        """
        saved_at = created_at or datetime.now()
        return self._execute_insert(
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
              realized_pnl,
              realized_pnl_rate,
              strategy_name,
              raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                realized_pnl,
                realized_pnl_rate,
                strategy_name,
                _json_text(raw_json),
            ),
            "insert_execution",
        )

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


def _datetime_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _trade_date_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
