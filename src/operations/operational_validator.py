import argparse
from dataclasses import dataclass, field

from src.db.query_repository import TradingQueryRepository
from src.report.report_parser import parse_report_date


ACTIVE_ORDER_STATUSES = {"REQUESTED", "ACCEPTED", "OPEN", "PARTIALLY_FILLED"}
CRITICAL_ORDER_STATUSES = {"UNFILLED_TIMEOUT", "RECONCILIATION_REQUIRED"}


@dataclass(frozen=True)
class OperationalValidation:
    trade_date: str
    passed: bool
    position_count: int
    active_order_count: int
    critical_order_count: int
    failed_order_count: int
    latest_snapshot_at: str | None
    realized_pnl_difference: float | None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def validate_operations(
    trade_date: str,
    repository: TradingQueryRepository | None = None,
) -> OperationalValidation:
    """Validate read-only operational state for one trading date.

    @param trade_date: Date in YYYY-MM-DD format.
    @param repository: Optional read-only query repository.
    @returns: Operational validation result.
    """
    query_repository = repository or TradingQueryRepository()
    orders = query_repository.get_orders(trade_date)
    positions = query_repository.get_current_positions()
    snapshot = query_repository.get_latest_account_snapshot(trade_date)
    active_orders = [row for row in orders if str(row.get("status")) in ACTIVE_ORDER_STATUSES]
    critical_orders = [row for row in orders if str(row.get("status")) in CRITICAL_ORDER_STATUSES]
    failed_orders = [row for row in orders if str(row.get("status")) == "FAILED"]
    blockers = []
    warnings = []

    is_available = getattr(query_repository, "is_available", lambda: True)
    if not is_available():
        blockers.append("database_unavailable")
    if active_orders:
        blockers.append(f"active_orders={len(active_orders)}")
    if critical_orders:
        blockers.append(f"critical_orders={len(critical_orders)}")
    if failed_orders:
        warnings.append(f"failed_orders={len(failed_orders)}")
    if snapshot is None:
        warnings.append("account_snapshot_missing")

    realized_pnl_difference = (
        float(snapshot["realized_pnl_difference"])
        if snapshot is not None and snapshot.get("realized_pnl_difference") is not None
        else None
    )
    if realized_pnl_difference not in (None, 0.0):
        warnings.append(f"realized_pnl_difference={realized_pnl_difference:g}")

    return OperationalValidation(
        trade_date=trade_date,
        passed=not blockers,
        position_count=len(positions),
        active_order_count=len(active_orders),
        critical_order_count=len(critical_orders),
        failed_order_count=len(failed_orders),
        latest_snapshot_at=str(snapshot.get("recorded_at")) if snapshot is not None else None,
        realized_pnl_difference=realized_pnl_difference,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def run_validation_command(argv: list[str] | None = None) -> int:
    """Run the read-only operational validation command.

    @param argv: Optional command arguments.
    @returns: 0 when no blockers exist, otherwise 2.
    """
    parser = argparse.ArgumentParser(description="Validate trading bot operational state")
    parser.add_argument("--date", default="today", help="Validation date: today or YYYY-MM-DD.")
    args = parser.parse_args(argv)
    result = validate_operations(parse_report_date(args.date))
    print(_format_validation(result))
    return 0 if result.passed else 2


def _format_validation(result: OperationalValidation) -> str:
    return "\n".join(
        [
            f"trade_date={result.trade_date}",
            f"status={'PASS' if result.passed else 'BLOCKED'}",
            f"positions={result.position_count}",
            f"active_orders={result.active_order_count}",
            f"critical_orders={result.critical_order_count}",
            f"failed_orders={result.failed_order_count}",
            f"latest_snapshot_at={result.latest_snapshot_at or 'NONE'}",
            (
                f"realized_pnl_difference={result.realized_pnl_difference:g}"
                if result.realized_pnl_difference is not None
                else "realized_pnl_difference=UNKNOWN"
            ),
            f"blockers={','.join(result.blockers) if result.blockers else 'NONE'}",
            f"warnings={','.join(result.warnings) if result.warnings else 'NONE'}",
        ]
    )
