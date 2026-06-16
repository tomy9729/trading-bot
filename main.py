import argparse
import sys
import time

from src.broker.kis_account import KisAccount
from src.broker.kis_client import KisClient
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.config.bot_config import load_bot_config
from src.config.env import load_settings
from src.logs.trade_logger import get_trade_logger
from src.runner.auto_trading_runner import AutoTradingRunner
from src.runner.dry_run_runner import DryRunRunner
from src.runner.live_runner import LiveRunner
from src.runner.market_hours import MarketHours
from src.watchlist.watchlist_manager import WatchlistManager


def main() -> int:
    """Run the trading bot command-line entrypoint.

    @returns: Process exit code.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        from src.report.daily_report import run_report_command

        return run_report_command(sys.argv[2:])

    parser = argparse.ArgumentParser(description="KIS VWAP volume-breakout trading bot")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "live", "monitor", "test-order", "test-buy", "test-sell"])
    parser.add_argument("--symbol", default="005930")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()

    logger = get_trade_logger()
    try:
        settings = load_settings()
        bot_config = load_bot_config()
        client = KisClient(settings)
        market_hours = MarketHours()
        market = KisMarket(client)
        account = KisAccount(client)
        order = KisOrder(client, market_hours)
        watchlist_manager = WatchlistManager(bot_config, market_hours, market)
        dry_runner = DryRunRunner(market, account, order)
        live_runner = LiveRunner(market, account, order)
        auto_runner = AutoTradingRunner(
            settings,
            bot_config,
            market_hours,
            market,
            account,
            order,
            watchlist_manager,
        )

        logger.info("[START] mode=%s market=domestic dry_run=%s mock=%s", args.mode, settings.dry_run, settings.kis_is_mock)
        if args.mode == "dry-run":
            result = live_runner.health_check(args.symbol)
            logger.info("[DRY-RUN READY] result=%s", result)
        elif args.mode == "live":
            if settings.dry_run:
                logger.info("[LIVE BLOCKED] DRY_RUN=true. Set DRY_RUN=false only after dry-run validation.")
                return 2
            result = live_runner.health_check(args.symbol)
            logger.info("[LIVE READY] result=%s", result)
        elif args.mode == "monitor":
            auto_runner.run_forever(args.interval_seconds)
        elif args.mode in {"test-order", "test-buy"}:
            dry_runner.test_buy(args.symbol, args.quantity)
        elif args.mode == "test-sell":
            dry_runner.test_sell(args.symbol, args.quantity)
        logger.info("[END] mode=%s", args.mode)
        return 0
    except Exception:
        logger.exception("[FATAL]")
        return 1


def _run_monitor(live_runner: LiveRunner, market_hours: MarketHours, args: argparse.Namespace) -> None:
    logger = get_trade_logger()
    while True:
        if not market_hours.is_domestic_open():
            logger.info("[MONITOR WAIT] market=domestic interval_seconds=%s", args.interval_seconds)
        else:
            try:
                result = live_runner.health_check(args.symbol)
                logger.info("[MONITOR CHECK] market=domestic result=%s", result)
            except Exception:
                logger.exception("[MONITOR CHECK FAILED] market=domestic")
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
