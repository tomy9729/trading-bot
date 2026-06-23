import sqlite3
from datetime import datetime

from src.db.repository import TradingRepository


def test_repository_creates_tables(tmp_path):
    db_path = tmp_path / "trading.db"

    TradingRepository(db_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('orders', 'executions', 'positions', 'account_snapshots')"
        ).fetchall()

    assert {row[0] for row in rows} == {"orders", "executions", "positions", "account_snapshots"}


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


def test_repository_updates_execution_financials(tmp_path):
    db_path = tmp_path / "trading.db"
    repository = TradingRepository(db_path)
    payload = {
        "order_id": "1",
        "symbol": "005930",
        "side": "SELL",
        "quantity": 1,
        "price": 70000,
        "created_at": datetime(2026, 6, 18, 9, 1, 2),
    }

    repository.insert_execution(**payload)
    repository.insert_execution(
        **payload,
        fee=10.5,
        tax=140,
        gross_pnl=1000,
        total_cost=161,
        realized_pnl=839,
        realized_pnl_rate=1.19,
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT fee, tax, gross_pnl, total_cost, realized_pnl, realized_pnl_rate FROM executions"
        ).fetchone()

    assert row == (10.5, 140.0, 1000.0, 161.0, 839.0, 1.19)


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


def test_repository_inserts_account_snapshot_and_reads_cumulative_cost(tmp_path):
    db_path = tmp_path / "trading.db"
    repository = TradingRepository(db_path)
    repository.insert_execution(
        order_id="1",
        symbol="005930",
        side="SELL",
        quantity=1,
        price=70000,
        fee=10,
        tax=140,
        created_at=datetime(2026, 6, 18, 9, 1, 2),
    )

    snapshot_id = repository.insert_account_snapshot(
        cash_balance=500000,
        available_cash=490000,
        stock_value=100000,
        total_asset=600000,
        unrealized_pnl=1000,
        daily_realized_pnl=-500,
        cumulative_cost=150,
        recorded_at=datetime(2026, 6, 18, 9, 5),
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT total_asset, cumulative_cost FROM account_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()

    assert row == (600000.0, 150.0)
    assert repository.get_cumulative_execution_cost("2026-06-18") == 150.0


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
