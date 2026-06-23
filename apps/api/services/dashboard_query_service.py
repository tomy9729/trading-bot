import json
from datetime import date
from typing import Any

from src.db.query_repository import TradingQueryRepository


class DashboardQueryService:
    def __init__(self, repository: TradingQueryRepository):
        """Create a read-only dashboard query service.

        @param repository: Trading data repository.
        """
        self.repository = repository

    def get_positions(self) -> list[dict[str, Any]]:
        """Return current positions without broker raw payloads.

        @returns: Dashboard position rows.
        """
        return [_without_fields(row, {"raw_json"}) for row in self.repository.get_current_positions()]

    def get_events(self, trade_date: date, limit: int) -> list[dict[str, Any]]:
        """Return normalized bot events for one date.

        @param trade_date: Trading date.
        @param limit: Maximum number of newest events.
        @returns: Dashboard event rows.
        """
        rows = self.repository.get_bot_events(trade_date.isoformat(), limit)
        return [_normalize_event(row) for row in rows]

    def get_orders(self, trade_date: date) -> list[dict[str, Any]]:
        """Return orders for one date without broker raw payloads.

        @param trade_date: Trading date.
        @returns: Dashboard order rows.
        """
        return [_without_fields(row, {"raw_json"}) for row in self.repository.get_orders(trade_date.isoformat())]

    def get_executions(self, trade_date: date) -> list[dict[str, Any]]:
        """Return executions for one date without broker raw payloads.

        @param trade_date: Trading date.
        @returns: Dashboard execution rows.
        """
        return [_without_fields(row, {"raw_json"}) for row in self.repository.get_executions(trade_date.isoformat())]

    def get_account_summary(self) -> dict[str, Any] | None:
        """Return the latest account summary without broker raw payloads.

        @returns: Latest account snapshot or None.
        """
        row = self.repository.get_latest_account_snapshot()
        return _without_fields(row, {"raw_json"}) if row is not None else None


def _normalize_event(row: dict[str, Any]) -> dict[str, Any]:
    result = _without_fields(row, {"payload_json"})
    payload_json = row.get("payload_json")
    if payload_json:
        try:
            result["details"] = json.loads(str(payload_json))
        except json.JSONDecodeError:
            result["details"] = {}
    else:
        result["details"] = {}
    return result


def _without_fields(row: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in fields}
