from dataclasses import replace

from src.config.env import Settings
from src.domain.market_data import MarketSnapshot
from src.domain.position import PositionState
from src.risk.risk_manager import RiskManager, RiskState
from src.strategy.advanced_signals import EntrySignal, MarketFilter, SymbolFilter

from tests.test_auto_trading_runner import _bot_config


def _settings() -> Settings:
    return Settings("key", "secret", "12345678", "01", False, True, None, 100000, 2, -2.0, 20000)


def _snapshot(**overrides) -> MarketSnapshot:
    data = {
        "symbol": "005930",
        "current_price": 1006,
        "vwap": 1000,
        "one_minute_volume": 3000,
        "previous_five_minute_average_volume": 1000,
        "recent_high": 1000,
        "daily_rise_rate": 1.0,
        "trade_value": 1_000_000_000,
        "spread_rate": 0.1,
        "vwap_hold_candle_count": 3,
        "upper_wick_rate": 10.0,
        "execution_strength": 70.0,
        "market_direction_rate": 0.5,
        "volume_declining": False,
    }
    data.update(overrides)
    return MarketSnapshot(**data)


def _entry_signal(bot_config=None) -> EntrySignal:
    config = bot_config or _bot_config()
    return EntrySignal(config, MarketFilter(config), SymbolFilter(config))


def _evaluate(snapshot: MarketSnapshot, bot_config=None):
    config = bot_config or _bot_config()
    return _entry_signal(config).evaluate(
        "KR",
        snapshot,
        PositionState(),
        RiskState(),
        RiskManager(_settings(), config.risk.max_daily_trade_count, config.risk.enforce_daily_loss_limit),
    )


def test_entry_blocks_when_breakout_volume_is_declining():
    signal = _evaluate(_snapshot(volume_declining=True))

    assert signal.allowed is False
    assert signal.reason == "VOLUME_DECLINING"
    assert "BREAKOUT_VOLUME_SUSTAINED" in signal.details["failed_conditions"]


def test_entry_blocks_chase_price_above_breakout_limit():
    config = replace(_bot_config(), strategy=replace(_bot_config().strategy, max_breakout_chase_percent=0.3))

    signal = _evaluate(_snapshot(current_price=1006, recent_high=1000), config)

    assert signal.allowed is False
    assert signal.reason == "CHASE_PRICE_TOO_HIGH"
    assert signal.details["breakout_chase_rate"] == 0.6


def test_upper_wick_filter_keeps_diagnostic_values():
    signal = _evaluate(_snapshot(upper_wick_rate=61.0))

    assert signal.allowed is False
    assert signal.reason == "UPPER_WICK_TOO_LONG"
    assert signal.details["max_upper_wick_percent"] == 60.0
    assert signal.details["upper_wick_excess_percent"] == 1.0
