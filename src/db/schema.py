from pathlib import Path

from src.db.connection import get_connection


def initialize_database(db_path: str | Path | None = None) -> None:
    """Create required trading tables and indexes.

    @param db_path: Optional SQLite database path.
    """
    with get_connection(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              trade_date TEXT NOT NULL,

              order_id TEXT,
              symbol TEXT NOT NULL,
              symbol_name TEXT,

              side TEXT NOT NULL,
              quantity INTEGER NOT NULL,
              price REAL,
              order_type TEXT NOT NULL,

              status TEXT NOT NULL,
              reason TEXT,
              strategy_name TEXT,

              raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS executions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              trade_date TEXT NOT NULL,

              order_id TEXT,
              symbol TEXT NOT NULL,
              symbol_name TEXT,

              side TEXT NOT NULL,
              quantity INTEGER NOT NULL,
              price REAL NOT NULL,

              fee REAL DEFAULT 0,
              tax REAL DEFAULT 0,
              realized_pnl REAL,
              realized_pnl_rate REAL,

              strategy_name TEXT,
              raw_json TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_executions_dedupe
            ON executions (
              COALESCE(order_id, ''),
              symbol,
              side,
              quantity,
              price,
              created_at
            );

            CREATE TABLE IF NOT EXISTS positions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              updated_at TEXT NOT NULL,
              trade_date TEXT NOT NULL,

              symbol TEXT NOT NULL UNIQUE,
              symbol_name TEXT,

              quantity INTEGER NOT NULL,
              avg_price REAL,
              current_price REAL,
              market_value REAL,
              unrealized_pnl REAL,
              unrealized_pnl_rate REAL,

              strategy_name TEXT,
              source TEXT DEFAULT 'KIS_API',

              raw_json TEXT
            );
            """
        )
