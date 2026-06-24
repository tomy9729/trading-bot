from datetime import datetime

from src.db.query_repository import TradingQueryRepository
from src.db.repository import TradingRepository


def test_query_repository_reads_dashboard_data_without_write_methods(tmp_path):
    db_path = tmp_path / "trading.db"
    writer = TradingRepository(db_path)
    writer.upsert_position(symbol="005930", quantity=1)
    writer.insert_bot_event(
        {
            "timestamp": "2026-06-23T09:30:00.000+09:00",
            "event_type": "info",
            "symbol": "005930",
        }
    )
    writer.insert_order(
        symbol="005930",
        side="BUY",
        quantity=1,
        order_type="MARKET",
        created_at=datetime(2026, 6, 23, 9, 30),
    )
    reader = TradingQueryRepository(db_path)

    assert [row["symbol"] for row in reader.get_current_positions()] == ["005930"]
    assert len(reader.get_bot_events("2026-06-23")) == 1
    assert len(reader.get_orders("2026-06-23")) == 1
    assert not hasattr(reader, "insert_order")
    assert reader.is_available() is True


def test_query_repository_does_not_create_missing_database(tmp_path):
    db_path = tmp_path / "missing.db"
    reader = TradingQueryRepository(db_path)

    assert reader.get_current_positions() == []
    assert db_path.exists() is False
    assert reader.is_available() is False
