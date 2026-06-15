from unittest.mock import Mock

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


def _settings(force_quantity=None) -> Settings:
    return Settings("key", "secret", "12345678", "01", False, True, force_quantity, 100000, 1, -2.0, 20000)


def _bot_config(order_krw: int = 20000, mode: str = "fractional_amount") -> BotConfig:
    return BotConfig(
        korea=KoreaMarketConfig(False, "09:00", "15:30", 10, 10, (("09:10", "11:00"),), ()),
        us=UsMarketConfig(True, "09:30", "16:00", "America/New_York", 15, 30, ()),
        strategy=StrategyConfig("test", 2.0, 5, 5, 3, 15.0, -2.0, 55.0, 0.3, 60.0, -0.5),
        risk=RiskConfig(
            max_buy_amount_per_trade=100000,
            us_order_amount_krw=order_krw,
            us_total_test_capital_krw=100000,
            us_max_symbol_exposure_krw=50000,
            us_assumed_usd_krw_rate=1400.0,
            us_fee_buffer_rate=0.005,
            us_max_buy_amount_per_trade_usd=15.0,
            us_order_mode=mode,
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
            kr=KrWatchlistConfig(False, "dynamic", 50, 180, 10, True, True, True, 1000, 0.3, 10000000),
            us=UsWatchlistConfig(True, "static", ("AAPL",), (), False, 0.2, True, True),
        ),
    )


def _runner(settings=None, bot_config=None) -> AutoTradingRunner:
    return AutoTradingRunner(
        settings or _settings(),
        bot_config or _bot_config(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
    )


def test_us_order_quantity_uses_configured_krw_amount_limit():
    runner = _runner(bot_config=_bot_config(order_krw=20000))
    assert runner._calculate_us_order_quantity("SPY", 100.0, 1000.0) > 0


def test_us_whole_share_mode_blocks_when_amount_cannot_buy_one_share():
    runner = _runner(bot_config=_bot_config(order_krw=20000, mode="whole_share_amount"))
    assert runner._calculate_us_order_quantity("SPY", 292.0, 1000.0) == 0


def test_us_force_quantity_overrides_amount_when_cash_is_enough():
    runner = _runner(settings=_settings(force_quantity=1), bot_config=_bot_config(order_krw=20000))
    assert runner._calculate_us_order_quantity("SPY", 292.0, 1000.0) == 1
