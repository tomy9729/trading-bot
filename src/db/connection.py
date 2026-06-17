import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data") / "trading.db"


def get_database_path(db_path: str | Path | None = None) -> Path:
    """Return the SQLite database path.

    @param db_path: Optional override path.
    @returns: Resolved database path.
    """
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create a SQLite connection for the trading database.

    @param db_path: Optional override path.
    @returns: SQLite connection.
    """
    path = get_database_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection
