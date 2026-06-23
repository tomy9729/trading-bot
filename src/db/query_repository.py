import logging
import sqlite3
from pathlib import Path
from typing import Any

from src.db.connection import get_read_connection


class TradingQueryRepository:
    def __init__(self, db_path: str | Path | None = None):
        """Create a read-only trading query repository.

        @param db_path: Optional SQLite database path.
        """
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

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

    def get_executions(self, trade_date: str) -> list[dict[str, Any]]:
        """Return executions saved for one trade date.

        @param trade_date: Date in YYYY-MM-DD format.
        @returns: Execution rows ordered by creation time.
        """
        return self._fetch_all(
            "SELECT * FROM executions WHERE trade_date = ? ORDER BY created_at, id",
            (trade_date,),
            "get_executions",
        )

    def get_current_positions(self) -> list[dict[str, Any]]:
        """Return current positive-quantity positions.

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

    def _fetch_all(self, sql: str, params: tuple[Any, ...], operation: str) -> list[dict[str, Any]]:
        try:
            with get_read_connection(self.db_path) as connection:
                rows = connection.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error:
            self.logger.exception("Trading DB read failed: operation=%s", operation)
            return []
