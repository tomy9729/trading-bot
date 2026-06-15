from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from src.config.bot_config import (
    BotConfig,
    KoreaMarketConfig,
    KrWatchlistConfig,
    RiskConfig,
    StrategyConfig,
    UsMarketConfig,
    UsWatchlistConfig,
    WatchlistConfig,
)
from src.config.env import Settings
from src.runner.auto_trading_runner import AutoTradingRunner


def _settings() -> Settings:
    return Settings("key", "secret", "12345678", "01", False, True, 1, 100000, 1, -2.0, 20000)


def _bot_config() -> BotConfig:
    return BotConfig(
        korea=KoreaMarketConfig(True, "09:00", "15:30", 10, 10, (("09:10", "11:00"),), ("005930",)),
        us=UsMarketConfig(False, "09:30", "16:00", "America/New_York", 15, 30, ()),
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
            us=UsWatchlistConfig(True, "static", ("AAPL",), (), False, 0.2, True, True),
        ),
    )


def _minute_rows():
    rows = []
    for index, price in enumerate([1000, 1001, 1002, 1003, 1004, 1006]):
        rows.append(
            {
                "stck_bsop_date": "20260615",
                "stck_cntg_hour": f"090{index}00",
                "stck_oprc": str(price),
                "stck_hgpr": str(price + (0 if index == 5 else 1)),
                "stck_lwpr": str(price - 1),
                "stck_prpr": str(price),
                "cntg_vol": "3000" if index == 5 else "1000",
            }
        )
    return rows


def test_auto_runner_places_domestic_dry_run_buy_when_signal_is_allowed():
    market_hours = Mock()
    market_hours.korea_tz = ZoneInfo("Asia/Seoul")
    market_hours.is_domestic_open.return_value = True
    market_hours.is_us_open.return_value = False

    domestic_market = Mock()
    domestic_market.get_minute_chart.return_value = _minute_rows()
    domestic_market.get_current_price.return_value = 1010
    domestic_market.get_orderbook.return_value = {"spread_rate": 0.1}

    domestic_account = Mock()
    domestic_account.get_balance.return_value = []
    domestic_account.get_available_cash.return_value = 100000

    domestic_order = Mock()
    domestic_order.buy_market.return_value = {"dry_run": True}
    watchlist_manager = Mock()
    watchlist_manager.get_symbols.return_value = ["005930"]
    watchlist_manager.is_watchable.return_value = True

    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        market_hours,
        domestic_market,
        domestic_account,
        domestic_order,
        Mock(),
        Mock(),
        Mock(),
        watchlist_manager,
    )
    runner._is_domestic_new_buy_blocked = Mock(return_value=False)

    runner.run_once()

    domestic_order.buy_market.assert_called_once_with("005930", 1)
