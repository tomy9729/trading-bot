import argparse
import sys
import time

from src.broker.kis_account import KisAccount
from src.broker.kis_client import KisClient
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.broker.kis_overseas_account import KisOverseasAccount
from src.broker.kis_overseas_market import KisOverseasMarket
from src.broker.kis_overseas_order import KisOverseasOrder
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
    parser = argparse.ArgumentParser(description="KIS VWAP volume-breakout trading bot")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "live", "monitor", "test-order", "test-buy", "test-sell"])
    parser.add_argument("--market", default="domestic", choices=["domestic", "us", "auto"])
    parser.add_argument("--symbol", default="005930")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--price", type=float, default=0.0, help="Required for live US limit orders.")
    parser.add_argument("--exchange", default="NASD", help="US order exchange: NASD, NYSE, or AMEX.")
    parser.add_argument("--quote-exchange", default="NAS", help="US quote exchange: NAS, NYS, or AMS.")
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
        overseas_market = KisOverseasMarket(client)
        overseas_account = KisOverseasAccount(client)
        overseas_order = KisOverseasOrder(client, market_hours)
        watchlist_manager = WatchlistManager(bot_config, market_hours, market, overseas_market)
        dry_runner = DryRunRunner(market, account, order, overseas_order)
        live_runner = LiveRunner(market, account, order, overseas_market, overseas_account, overseas_order)
        auto_runner = AutoTradingRunner(
            settings,
            bot_config,
            market_hours,
            market,
            account,
            order,
            overseas_market,
            overseas_account,
            overseas_order,
            watchlist_manager,
        )

        logger.info("[START] mode=%s market=%s dry_run=%s mock=%s", args.mode, args.market, settings.dry_run, settings.kis_is_mock)
        if args.mode == "dry-run":
            selected_market = _resolve_market(args.market, market_hours)
            result = _health_check(live_runner, selected_market, args)
            logger.info("[DRY-RUN READY] result=%s", result)
        elif args.mode == "live":
            if settings.dry_run:
                logger.info("[LIVE BLOCKED] DRY_RUN=true. Set DRY_RUN=false only after dry-run validation.")
                return 2
            selected_market = _resolve_market(args.market, market_hours)
            result = _health_check(live_runner, selected_market, args)
            logger.info("[LIVE READY] result=%s", result)
        elif args.mode == "monitor":
            auto_runner.run_forever(args.interval_seconds)
        elif args.mode in {"test-order", "test-buy"}:
            if _resolve_market(args.market, market_hours, allow_closed=True) == "us":
                _require_us_price(args.price, settings.dry_run)
                dry_runner.test_us_buy(args.symbol, args.quantity, args.price, args.exchange)
            else:
                dry_runner.test_buy(args.symbol, args.quantity)
        elif args.mode == "test-sell":
            if _resolve_market(args.market, market_hours, allow_closed=True) == "us":
                _require_us_price(args.price, settings.dry_run)
                dry_runner.test_us_sell(args.symbol, args.quantity, args.price, args.exchange)
            else:
                dry_runner.test_sell(args.symbol, args.quantity)
        logger.info("[END] mode=%s", args.mode)
        return 0
    except Exception:
        logger.exception("[FATAL]")
        return 1


def _resolve_market(market: str, market_hours: MarketHours, allow_closed: bool = False) -> str:
    if market != "auto":
        return market
    active_market = market_hours.get_active_market()
    if active_market is not None:
        return active_market
    if allow_closed:
        return "domestic"
    raise RuntimeError("No supported market is currently open.")


def _health_check(live_runner: LiveRunner, market: str, args: argparse.Namespace) -> dict:
    if market == "us":
        return live_runner.overseas_health_check(args.symbol, args.quote_exchange, args.exchange)
    return live_runner.health_check(args.symbol)


def _run_monitor(live_runner: LiveRunner, market_hours: MarketHours, args: argparse.Namespace) -> None:
    logger = get_trade_logger()
    while True:
        active_market = args.market if args.market != "auto" else market_hours.get_active_market()
        if active_market is None or not market_hours.is_open(active_market):
            logger.info("[MONITOR WAIT] market=%s interval_seconds=%s", args.market, args.interval_seconds)
        else:
            try:
                result = _health_check(live_runner, active_market, args)
                logger.info("[MONITOR CHECK] market=%s result=%s", active_market, result)
            except Exception:
                logger.exception("[MONITOR CHECK FAILED] market=%s", active_market)
        time.sleep(args.interval_seconds)


def _require_us_price(price: float, dry_run: bool) -> None:
    if price <= 0 and not dry_run:
        raise ValueError("--price is required for live US limit orders.")
    if price <= 0:
        raise ValueError("--price is required for US limit-order dry-run logs too.")


if __name__ == "__main__":
    sys.exit(main())
