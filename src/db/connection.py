import sqlite3
from pathlib import Path

from src.config.runtime_paths import get_database_path as get_default_database_path


def get_database_path(db_path: str | Path | None = None) -> Path:
    """Return the SQLite database path.

    @param db_path: Optional override path.
    @returns: Resolved database path.
    """
    return Path(db_path) if db_path is not None else get_default_database_path()


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create a SQLite connection for the trading database.

    @param db_path: Optional override path.
    @returns: SQLite connection.
    """
    path = get_database_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def get_read_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create a read-only SQLite connection for dashboard queries.

    @param db_path: Optional override path.
    @returns: Read-only SQLite connection.
    """
    path = get_database_path(db_path).resolve()
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
