from datetime import date, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from apps.api.dependencies import get_trading_repository
from apps.api.services.dashboard_query_service import DashboardQueryService
from src.db.query_repository import TradingQueryRepository


router = APIRouter(prefix="/api/v1", tags=["dashboard"])
RepositoryDependency = Annotated[TradingQueryRepository, Depends(get_trading_repository)]


@router.get("/health")
def get_health() -> dict[str, str]:
    """Return API health information.

    @returns: API status and roadmap version.
    """
    return {"status": "ok", "version": "0.9.0"}


@router.get("/positions")
def get_positions(repository: RepositoryDependency) -> dict[str, list[dict[str, Any]]]:
    """Return current bot positions.

    @param repository: Injected trading repository.
    @returns: Current position collection.
    """
    return {"items": DashboardQueryService(repository).get_positions()}


@router.get("/events")
def get_events(
    repository: RepositoryDependency,
    trade_date: date | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """Return bot events for one trading date.

    @param repository: Injected trading repository.
    @param trade_date: Trading date, defaulting to today.
    @param limit: Maximum number of newest events.
    @returns: Event collection and selected date.
    """
    selected_date = trade_date or _get_korea_date()
    return {
        "trade_date": selected_date.isoformat(),
        "items": DashboardQueryService(repository).get_events(selected_date, limit),
    }


@router.get("/orders")
def get_orders(repository: RepositoryDependency, trade_date: date | None = None) -> dict[str, Any]:
    """Return orders for one trading date.

    @param repository: Injected trading repository.
    @param trade_date: Trading date, defaulting to today.
    @returns: Order collection and selected date.
    """
    selected_date = trade_date or _get_korea_date()
    return {
        "trade_date": selected_date.isoformat(),
        "items": DashboardQueryService(repository).get_orders(selected_date),
    }


@router.get("/executions")
def get_executions(repository: RepositoryDependency, trade_date: date | None = None) -> dict[str, Any]:
    """Return executions for one trading date.

    @param repository: Injected trading repository.
    @param trade_date: Trading date, defaulting to today.
    @returns: Execution collection and selected date.
    """
    selected_date = trade_date or _get_korea_date()
    return {
        "trade_date": selected_date.isoformat(),
        "items": DashboardQueryService(repository).get_executions(selected_date),
    }


@router.get("/account-summary")
def get_account_summary(repository: RepositoryDependency) -> dict[str, Any]:
    """Return the latest account snapshot.

    @param repository: Injected trading repository.
    @returns: Latest account snapshot.
    """
    return {"item": DashboardQueryService(repository).get_account_summary()}


def _get_korea_date() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()
