from dataclasses import replace

from src.config.env import Settings
from src.domain.market_data import MarketSnapshot, MinuteCandle
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


def test_entry_allows_one_miss_relaxed_volume_spike_candidate():
    config = replace(
        _bot_config(),
        strategy=replace(
            _bot_config().strategy,
            volume_multiplier=2.0,
            relaxed_volume_multiplier=0.84,
            relaxed_vwap_hold_candles=2,
        ),
    )

    signal = _evaluate(_snapshot(one_minute_volume=900), config)

    assert signal.allowed is True
    assert signal.reason == "CONDITIONAL_RELAXED_VOLUME_SPIKE"
    assert signal.details["relaxed_conditions"] == ("VOLUME_SPIKE",)


def test_entry_allows_one_miss_relaxed_vwap_hold_candidate():
    config = replace(
        _bot_config(),
        strategy=replace(
            _bot_config().strategy,
            vwap_hold_candles=5,
            relaxed_vwap_hold_candles=2,
        ),
    )

    signal = _evaluate(_snapshot(vwap_hold_candle_count=2), config)

    assert signal.allowed is True
    assert signal.reason == "CONDITIONAL_RELAXED_VWAP_HOLD"
    assert signal.details["relaxed_conditions"] == ("VWAP_HOLD",)


def test_entry_blocks_when_multiple_conditions_need_relaxation():
    config = replace(
        _bot_config(),
        strategy=replace(
            _bot_config().strategy,
            volume_multiplier=2.0,
            relaxed_volume_multiplier=0.84,
            vwap_hold_candles=5,
            relaxed_vwap_hold_candles=2,
        ),
    )

    signal = _evaluate(_snapshot(one_minute_volume=900, vwap_hold_candle_count=2), config)

    assert signal.allowed is False
    assert signal.reason == "MULTIPLE_RELAXED_CONDITIONS"


def test_entry_allows_pullback_reentry_near_vwap():
    config = replace(
        _bot_config(),
        strategy=replace(
            _bot_config().strategy,
            entry_mode="breakout_or_pullback",
            pullback_enabled=True,
            pullback_near_vwap_percent=0.5,
            pullback_max_depth_percent=2.0,
            pullback_volume_cooldown_ratio=0.8,
        ),
    )
    candles = (
        MinuteCandle("1", 1000, 1010, 990, 1005, 1000),
        MinuteCandle("2", 1005, 1020, 1000, 1018, 1000),
        MinuteCandle("3", 1010, 1014, 1004, 1012, 600),
    )

    signal = _evaluate(
        _snapshot(
            current_price=1002,
            vwap=1000,
            recent_high=1020,
            one_minute_volume=600,
            previous_five_minute_average_volume=1000,
            execution_strength=70.0,
            candles=candles,
        ),
        config,
    )

    assert signal.allowed is True
    assert signal.reason == "PULLBACK_REENTRY"
    assert signal.details["entry_reason"] == "PULLBACK_REENTRY"


def test_pullback_only_blocks_breakout_chase():
    config = replace(
        _bot_config(),
        strategy=replace(_bot_config().strategy, entry_mode="pullback_only", pullback_enabled=True),
    )

    signal = _evaluate(_snapshot(current_price=1008, recent_high=1000), config)

    assert signal.allowed is False
    assert signal.reason == "NOT_CHASING_BREAKOUT"
