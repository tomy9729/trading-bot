import argparse
from pathlib import Path

from src.config.bot_config import load_bot_config
from src.report.missed_trade_analyzer import analyze_missed_candidates
from src.report.report_analyzer import analyze_trades
from src.report.report_parser import get_default_log_path, parse_log_file, parse_report_date
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
    analysis = analyze_trades(events)
    missed_candidates = analyze_missed_candidates(events, bot_config)
    report_path = write_report(report_date, analysis, missed_candidates, args.save)
    if report_path is not None:
        print(f"Report saved: {report_path}")
    elif not events:
        print(f"Log file not found or empty: {log_path}")
    return 0
