from pathlib import Path

from src.db.connection import get_connection


def initialize_database(db_path: str | Path | None = None) -> None:
    """Create required trading tables and indexes.

    @param db_path: Optional SQLite database path.
    """
    with get_connection(db_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
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

            CREATE TABLE IF NOT EXISTS account_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              recorded_at TEXT NOT NULL,
              trade_date TEXT NOT NULL,

              cash_balance REAL,
              available_cash REAL,
              stock_value REAL,
              total_asset REAL,
              unrealized_pnl REAL,
              daily_realized_pnl REAL,
              cumulative_cost REAL,
              broker_daily_realized_pnl REAL,
              realized_pnl_difference REAL,

              raw_json TEXT
            );

            CREATE INDEX IF NOT EXISTS ix_account_snapshots_recorded_at
            ON account_snapshots (recorded_at);

            CREATE TABLE IF NOT EXISTS bot_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_time TEXT NOT NULL,
              trade_date TEXT NOT NULL,
              event_type TEXT NOT NULL,

              market TEXT,
              symbol TEXT,
              symbol_name TEXT,
              side TEXT,
              quantity INTEGER,
              price REAL,
              reason TEXT,
              message TEXT,

              payload_json TEXT,
              created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_bot_events_trade_date_time
            ON bot_events (trade_date, event_time, id);

            CREATE INDEX IF NOT EXISTS ix_bot_events_type
            ON bot_events (event_type);
            """
        )
        _ensure_column(connection, "executions", "gross_pnl", "REAL")
        _ensure_column(connection, "executions", "total_cost", "REAL DEFAULT 0")
        _ensure_column(connection, "account_snapshots", "broker_daily_realized_pnl", "REAL")
        _ensure_column(connection, "account_snapshots", "realized_pnl_difference", "REAL")


def _ensure_column(connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
