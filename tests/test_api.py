from datetime import date
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from apps.api.app import create_app
from apps.api.dependencies import get_trading_repository
from src.db.repository import TradingRepository


class _FakeRepository:
    def get_current_positions(self):
        return [{"symbol": "005930", "quantity": 1, "raw_json": "{}"}]

    def get_bot_events(self, trade_date: str, limit: int | None = None):
        return [
            {
                "event_type": "order_skipped",
                "trade_date": trade_date,
                "symbol": "005930",
                "payload_json": '{"reason": "TEST"}',
            }
        ][:limit]

    def get_orders(self, trade_date: str):
        return [{"trade_date": trade_date, "symbol": "005930", "raw_json": "{}"}]

    def get_executions(self, trade_date: str):
        return [{"trade_date": trade_date, "symbol": "005930", "raw_json": "{}"}]

    def get_latest_account_snapshot(self):
        return {"total_asset": 1000000, "raw_json": "{}"}


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_trading_repository] = _FakeRepository
    return TestClient(app)


def test_dashboard_api_health():
    response = _client().get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_api_returns_read_only_dashboard_data():
    client = _client()
    selected_date = date(2026, 6, 23).isoformat()

    positions = client.get("/api/v1/positions").json()["items"]
    events = client.get("/api/v1/events", params={"trade_date": selected_date, "limit": 10}).json()
    orders = client.get("/api/v1/orders", params={"trade_date": selected_date}).json()["items"]
    executions = client.get("/api/v1/executions", params={"trade_date": selected_date}).json()["items"]
    account_summary = client.get("/api/v1/account-summary").json()["item"]

    assert positions == [{"symbol": "005930", "quantity": 1}]
    assert events["trade_date"] == selected_date
    assert events["items"][0]["details"]["reason"] == "TEST"
    assert "raw_json" not in orders[0]
    assert "raw_json" not in executions[0]
    assert account_summary == {"total_asset": 1000000}


def test_dashboard_api_reads_while_bot_repository_writes(tmp_path):
    repository = TradingRepository(tmp_path / "trading.db")
    app = create_app()
    app.dependency_overrides[get_trading_repository] = lambda: repository
    client = TestClient(app)

    def write_events():
        for index in range(20):
            repository.insert_bot_event(
                {
                    "timestamp": f"2026-06-23T09:30:{index:02d}.000+09:00",
                    "event_type": "info",
                    "symbol": "005930",
                    "message": f"event-{index}",
                }
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        write_future = executor.submit(write_events)
        read_future = executor.submit(
            lambda: client.get(
                "/api/v1/events",
                params={"trade_date": "2026-06-23", "limit": 20},
            )
        )

    assert write_future.exception() is None
    assert read_future.result().status_code == 200
    assert len(repository.get_bot_events("2026-06-23")) == 20
