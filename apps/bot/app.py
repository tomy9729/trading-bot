import argparse
import sys

from src.broker.kis_account import KisAccount
from src.broker.kis_client import KisClient
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.config.bot_config import load_bot_config
from src.config.env import load_settings
from src.config.strategy_metadata import create_strategy_metadata
from src.db.repository import TradingRepository
from src.logs.trade_logger import get_trade_logger, set_trade_event_sink
from src.runner.auto_trading_runner import AutoTradingRunner
from src.runner.dry_run_runner import DryRunRunner
from src.runner.live_runner import LiveRunner
from src.runner.market_hours import MarketHours
from src.services.trading_order_service import TradingOrderService
from src.watchlist.watchlist_manager import WatchlistManager


def main() -> int:
    """Run the trading bot command-line application.

    @returns: Process exit code.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        from src.report.daily_report import run_report_command

        return run_report_command(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        from src.operations.operational_validator import run_validation_command

        return run_validation_command(sys.argv[2:])

    parser = argparse.ArgumentParser(description="KIS VWAP volume-breakout trading bot")
    parser.add_argument(
        "--mode",
        default="dry-run",
        choices=["dry-run", "live", "monitor", "recover", "test-order", "test-buy", "test-sell"],
    )
    parser.add_argument("--symbol", default="005930")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()

    logger = get_trade_logger()
    try:
        settings = load_settings()
        bot_config = load_bot_config()
        strategy_metadata = create_strategy_metadata(bot_config)
        trade_repository = TradingRepository()
        set_trade_event_sink(trade_repository.insert_bot_event)
        client = KisClient(settings)
        market_hours = MarketHours()
        market = KisMarket(client)
        account = KisAccount(client)
        broker_order = KisOrder(client, market_hours)
        order = TradingOrderService(
            settings,
            broker_order,
            trade_repository,
            strategy_name=strategy_metadata["strategy_name"],
            strategy_version=strategy_metadata["strategy_version"],
            applied_config=strategy_metadata["applied_config"],
        )
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
            trade_repository,
        )

        logger.info(
            "[START] mode=%s market=domestic dry_run=%s mock=%s",
            args.mode,
            settings.dry_run,
            settings.kis_is_mock,
        )
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
        elif args.mode == "recover":
            auto_runner.recover_once(save_snapshot=True)
            logger.info(
                "[RECOVERY COMPLETE] safe_mode=%s reasons=%s positions=%s pending_orders=%s",
                auto_runner.state.safe_mode,
                sorted(auto_runner.state.kill_switch_reasons),
                sorted(auto_runner.state.positions),
                sorted(auto_runner.state.pending_order_symbols),
            )
            return 2 if auto_runner.state.safe_mode else 0
        elif args.mode in {"test-order", "test-buy"}:
            dry_runner.test_buy(args.symbol, args.quantity)
        elif args.mode == "test-sell":
            dry_runner.test_sell(args.symbol, args.quantity)
        logger.info("[END] mode=%s", args.mode)
        return 0
    except Exception:
        logger.exception("[FATAL]")
        return 1
