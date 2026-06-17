import sqlite3
from datetime import datetime

from src.db.repository import TradingRepository


def test_repository_creates_tables(tmp_path):
    db_path = tmp_path / "trading.db"

    TradingRepository(db_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('orders', 'executions', 'positions')"
        ).fetchall()

    assert {row[0] for row in rows} == {"orders", "executions", "positions"}


def test_repository_inserts_order_and_updates_status(tmp_path):
    db_path = tmp_path / "trading.db"
    repository = TradingRepository(db_path)

    order_row_id = repository.insert_order(
        symbol="005930",
        side="BUY",
        quantity=1,
        price=0,
        order_type="MARKET",
        status="REQUESTED",
    )
    repository.update_order_status(order_row_id=order_row_id, order_id="1", status="ACCEPTED")

    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT order_id, status FROM orders WHERE id = ?", (order_row_id,)).fetchone()

    assert row == ("1", "ACCEPTED")


def test_repository_ignores_duplicate_executions(tmp_path):
    db_path = tmp_path / "trading.db"
    repository = TradingRepository(db_path)
    payload = {
        "order_id": "1",
        "symbol": "005930",
        "side": "BUY",
        "quantity": 1,
        "price": 70000,
        "created_at": datetime(2026, 6, 18, 9, 1, 2),
    }

    first_id = repository.insert_execution(**payload)
    second_id = repository.insert_execution(**payload)

    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM executions").fetchone()[0]

    assert first_id is not None
    assert second_id is None
    assert count == 1


def test_repository_ignores_duplicate_executions_without_order_id(tmp_path):
    db_path = tmp_path / "trading.db"
    repository = TradingRepository(db_path)
    payload = {
        "symbol": "005930",
        "side": "BUY",
        "quantity": 1,
        "price": 70000,
        "created_at": datetime(2026, 6, 18, 9, 1, 2),
    }

    first_id = repository.insert_execution(**payload)
    second_id = repository.insert_execution(**payload)

    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM executions").fetchone()[0]

    assert first_id is not None
    assert second_id is None
    assert count == 1


def test_repository_upserts_position_by_symbol(tmp_path):
    db_path = tmp_path / "trading.db"
    repository = TradingRepository(db_path)

    repository.upsert_position(symbol="005930", symbol_name="Samsung", quantity=1, avg_price=70000)
    repository.upsert_position(symbol="005930", symbol_name="Samsung", quantity=2, avg_price=71000)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT symbol, quantity, avg_price FROM positions").fetchall()

    assert rows == [("005930", 2, 71000)]


def test_repository_does_not_raise_when_db_save_fails(tmp_path):
    repository = TradingRepository(tmp_path)

    order_row_id = repository.insert_order(
        symbol="005930",
        side="BUY",
        quantity=1,
        order_type="MARKET",
    )
    updated = repository.update_order_status(order_row_id=1, status="FAILED")

    assert order_row_id is None
    assert updated is False
