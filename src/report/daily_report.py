import argparse
from datetime import datetime
from pathlib import Path

from src.config.bot_config import load_bot_config
from src.config.strategy_metadata import create_strategy_metadata
from src.db.repository import TradingRepository
from src.report.missed_trade_analyzer import analyze_missed_candidates
from src.report.report_analyzer import analyze_trades
from src.report.report_parser import ReportEvent, get_default_log_path, parse_log_file, parse_report_date
from src.report.report_writer import write_report


def run_report_command(argv: list[str] | None = None) -> int:
    """Run the daily trading report command.

    @param argv: Optional report command arguments.
    @returns: Process exit code.
    """
    parser = argparse.ArgumentParser(description="Create a daily trading report from trade logs")
    parser.add_argument("--date", default="today", help="Report date: today or YYYY-MM-DD.")
    parser.add_argument("--save", action="store_true", help="Save report to reports/YYYY-MM-DD-daily-trading-report.md.")
    parser.add_argument("--log-path", default=None, help="Optional log path override.")
    args = parser.parse_args(argv)

    report_date = parse_report_date(args.date)
    log_path = Path(args.log_path) if args.log_path is not None else get_default_log_path(report_date)
    events = parse_log_file(log_path)
    bot_config = load_bot_config()
    repository = TradingRepository()
    execution_rows = repository.get_executions(report_date)
    account_snapshot = repository.get_latest_account_snapshot(report_date)
    analysis_events = _replace_order_events_with_executions(events, execution_rows)
    analysis = analyze_trades(analysis_events, bot_config.cost)
    missed_candidates = analyze_missed_candidates(events, bot_config)
    report_path = write_report(
        report_date,
        analysis,
        missed_candidates,
        args.save,
        account_snapshot=account_snapshot,
        strategy_metadata=create_strategy_metadata(bot_config),
    )
    if report_path is not None:
        print(f"Report saved: {report_path}")
    elif not events:
        print(f"Log file not found or empty: {log_path}")
    return 0


def _replace_order_events_with_executions(
    events: list[ReportEvent],
    execution_rows: list[dict],
) -> list[ReportEvent]:
    if not execution_rows:
        return events
    analysis_events = [
        event
        for event in events
        if event.event_type not in {"BUY_ORDER_FILLED", "SELL_ORDER_FILLED"}
    ]
    for row in execution_rows:
        side = str(row.get("side") or "")
        if side not in {"BUY", "SELL"}:
            continue
        price_key = "entry_price" if side == "BUY" else "exit_price"
        analysis_events.append(
            ReportEvent(
                timestamp=datetime.strptime(str(row["created_at"]), "%Y-%m-%d %H:%M:%S"),
                event_type=f"{side}_ORDER_FILLED",
                message="DB execution",
                data={
                    "symbol": row.get("symbol"),
                    "name": row.get("symbol_name"),
                    "quantity": row.get("quantity"),
                    price_key: row.get("price"),
                    "fee": row.get("fee"),
                    "tax": row.get("tax"),
                    "gross_pnl": row.get("gross_pnl"),
                    "total_cost": row.get("total_cost"),
                    "realized_pnl": row.get("realized_pnl"),
                    "realized_pnl_rate": row.get("realized_pnl_rate"),
                },
            )
        )
    return sorted(analysis_events, key=lambda event: event.timestamp)
