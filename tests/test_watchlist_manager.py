from unittest.mock import Mock

from src.config.bot_config import (
    BotConfig,
    KoreaMarketConfig,
    KrWatchlistConfig,
    RiskConfig,
    StrategyConfig,
    UsMarketConfig,
    UsWatchItem,
    UsWatchlistConfig,
    WatchlistConfig,
)
from src.watchlist.watchlist_manager import WatchlistManager


def _bot_config(use_optional_symbols: bool = False) -> BotConfig:
    return BotConfig(
        korea=KoreaMarketConfig(True, "09:00", "15:30", 10, 10, (("09:10", "11:00"),), ("005930",)),
        us=UsMarketConfig(
            True,
            "09:30",
            "16:00",
            "America/New_York",
            15,
            30,
            (UsWatchItem("AAPL", "NAS", "NASD"), UsWatchItem("AVGO", "NAS", "NASD")),
        ),
        strategy=StrategyConfig("test", 2.0, 5, 5, 2, 15.0, -2.0, 55.0, 0.3, 60.0, -0.5),
        risk=RiskConfig(
            max_buy_amount_per_trade=100000,
            us_order_amount_krw=20000,
            us_total_test_capital_krw=100000,
            us_max_symbol_exposure_krw=50000,
            us_assumed_usd_krw_rate=1400.0,
            us_fee_buffer_rate=0.005,
            us_max_buy_amount_per_trade_usd=15.0,
            us_order_mode="fractional_amount",
            us_fractional_order_enabled=False,
            max_daily_loss=5000,
            max_daily_loss_percent=-1.5,
            max_daily_trade_count=5,
            max_position_count=2,
            take_profit_percent=0.8,
            second_take_profit_percent=1.7,
            partial_take_profit_ratio=0.5,
            stop_loss_percent=-0.7,
            break_even_stop_percent=0.0,
            stale_position_minutes=5,
            stale_position_min_profit_percent=0.5,
            unfilled_order_timeout_seconds=30,
            reentry_cooldown_minutes=15,
        ),
        watchlist=WatchlistConfig(
            kr=KrWatchlistConfig(True, "dynamic", 50, 180, 10, True, True, True, 1000, 0.3, 10000000),
            us=UsWatchlistConfig(True, "static", ("AAPL",), ("AVGO",), use_optional_symbols, 0.2, True, True),
        ),
    )


def test_us_watchlist_uses_optional_symbols_only_when_enabled():
    market_hours = Mock()
    market_hours.is_us_open.return_value = True
    overseas_market = Mock()
    overseas_market.get_orderbook.return_value = {"spread_rate": 0.1}

    manager = WatchlistManager(_bot_config(False), market_hours, Mock(), overseas_market)
    manager.refresh("US", force=True)
    assert manager.get_symbols("US") == ["AAPL"]

    manager = WatchlistManager(_bot_config(True), market_hours, Mock(), overseas_market)
    manager.refresh("US", force=True)
    assert manager.get_symbols("US") == ["AAPL", "AVGO"]


def test_kr_watchlist_excludes_wide_spread_symbol():
    domestic_market = Mock()
    domestic_market.get_trading_value_rank.return_value = [{"mksc_shrn_iscd": "005930"}]
    domestic_market.get_current_price.return_value = 70000
    domestic_market.get_orderbook.return_value = {"spread_rate": 0.5, "depth_value": 100000000}

    manager = WatchlistManager(_bot_config(), Mock(), domestic_market, Mock())
    manager.refresh("KR", force=True)

    assert manager.get_symbols("KR") == []
    assert manager.get_exclude_reason("KR", "005930") == "wide_spread"
