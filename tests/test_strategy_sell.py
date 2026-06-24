from datetime import datetime, timedelta

from src.domain.market_data import MarketSnapshot
from src.domain.position import Position
from src.config.bot_config import load_bot_config
from src.strategy.advanced_signals import ExitSignal
from src.strategy.vwap_volume_breakout import should_sell


def _market(**overrides) -> MarketSnapshot:
    data = {
        "symbol": "005930",
        "current_price": 1012,
        "vwap": 1000,
        "one_minute_volume": 0,
        "previous_five_minute_average_volume": 0,
        "recent_high": 0,
        "daily_rise_rate": 0.0,
        "trade_value": 0,
        "spread_rate": 0.0,
    }
    data.update(overrides)
    return MarketSnapshot(**data)


def _position(now: datetime) -> Position:
    return Position("005930", 1, 1000, now - timedelta(minutes=1))


def test_take_profit_signal():
    now = datetime(2026, 1, 1, 10, 0)
    signal = should_sell(_position(now), _market(current_price=1020), now)
    assert signal.reason == "TAKE_PROFIT"


def test_stop_loss_signal():
    now = datetime(2026, 1, 1, 10, 0)
    signal = should_sell(_position(now), _market(current_price=990), now)
    assert signal.reason == "STOP_LOSS"


def test_vwap_breakdown_signal():
    now = datetime(2026, 1, 1, 10, 0)
    signal = should_sell(_position(now), _market(current_price=1000, vwap=1001), now)
    assert signal.reason == "VWAP_BREAKDOWN"


def test_time_exit_signal():
    now = datetime(2026, 1, 1, 10, 20)
    position = Position("005930", 1, 1000, now - timedelta(minutes=15))
    signal = should_sell(position, _market(current_price=1001), now)
    assert signal.reason == "TIME_EXIT"


def test_force_exit_signal():
    now = datetime(2026, 1, 1, 15, 15)
    signal = should_sell(_position(now), _market(current_price=1001), now)
    assert signal.reason == "FORCE_EXIT"


def test_volume_decline_does_not_exit_when_estimated_net_profit_is_negative():
    now = datetime(2026, 1, 1, 10, 0)
    signal = ExitSignal(load_bot_config()).evaluate(
        _position(now),
        _market(
            current_price=1001,
            vwap=999,
            volume_declining=True,
            market_direction_rate=0.0,
        ),
        now,
    )

    assert signal.allowed is False
    assert signal.reason == "EXIT_CONDITION_NOT_MET"
    assert signal.details["gross_profit_rate"] == 0.1
    assert signal.details["net_profit_rate"] < 0


def test_volume_decline_does_not_exit_when_estimated_net_profit_is_positive():
    now = datetime(2026, 1, 1, 10, 0)
    signal = ExitSignal(load_bot_config()).evaluate(
        _position(now),
        _market(
            current_price=1005,
            vwap=999,
            recent_high=1000,
            volume_declining=True,
            market_direction_rate=0.0,
        ),
        now,
    )

    assert signal.allowed is False
    assert signal.reason == "EXIT_CONDITION_NOT_MET"


def test_volume_decline_exits_when_breakout_is_not_held():
    now = datetime(2026, 1, 1, 10, 0)
    signal = ExitSignal(load_bot_config()).evaluate(
        _position(now),
        _market(
            current_price=1005,
            vwap=999,
            recent_high=1005,
            volume_declining=True,
            market_direction_rate=0.0,
        ),
        now,
    )

    assert signal.allowed is True
    assert signal.reason == "VOLUME_DROPPED_AFTER_BREAKOUT"
