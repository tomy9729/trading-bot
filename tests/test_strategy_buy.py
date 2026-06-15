from src.config.env import Settings
from src.domain.market_data import MarketSnapshot
from src.domain.position import PositionState
from src.risk.risk_manager import RiskManager, RiskState
from src.strategy.vwap_volume_breakout import should_buy


def _settings() -> Settings:
    return Settings("key", "secret", "12345678", "01", False, True, None, 100000, 1, -2.0, 20000)


def _snapshot(**overrides) -> MarketSnapshot:
    data = {
        "symbol": "005930",
        "current_price": 72300,
        "vwap": 71950,
        "one_minute_volume": 3100,
        "previous_five_minute_average_volume": 1000,
        "recent_high": 72100,
        "daily_rise_rate": 5.0,
        "trade_value": 6_000_000_000,
        "spread_rate": 0.15,
    }
    data.update(overrides)
    return MarketSnapshot(**data)


def _buy_signal(snapshot: MarketSnapshot, risk_state: RiskState | None = None):
    return should_buy(snapshot, PositionState(), risk_state or RiskState(), RiskManager(_settings()))


def test_buy_when_all_conditions_are_met():
    signal = _buy_signal(_snapshot())
    assert signal.signal == "BUY"
    assert signal.allowed is True
    assert signal.reason == "VWAP_ABOVE_AND_VOLUME_BREAKOUT"


def test_no_buy_when_price_is_below_vwap():
    signal = _buy_signal(_snapshot(current_price=71800))
    assert signal.signal == "HOLD"
    assert signal.reason == "PRICE_NOT_ABOVE_VWAP"


def test_no_buy_when_volume_multiplier_is_too_low():
    signal = _buy_signal(_snapshot(one_minute_volume=1999))
    assert signal.reason == "VOLUME_SPIKE_NOT_ENOUGH"


def test_no_buy_when_breakout_fails():
    signal = _buy_signal(_snapshot(current_price=72100, recent_high=72100))
    assert signal.reason == "BREAKOUT_FAILED"


def test_no_buy_when_daily_rise_rate_is_too_high():
    signal = _buy_signal(_snapshot(daily_rise_rate=15.1))
    assert signal.reason == "DAILY_RISE_RATE_TOO_HIGH"


def test_trade_value_does_not_block_when_not_configured():
    signal = _buy_signal(_snapshot(trade_value=0))
    assert signal.signal == "BUY"


def test_no_buy_when_spread_rate_is_too_high():
    signal = _buy_signal(_snapshot(spread_rate=0.31))
    assert signal.reason == "SPREAD_RATE_TOO_HIGH"


def test_no_buy_when_symbol_is_already_held_by_risk_state():
    signal = _buy_signal(_snapshot(), RiskState(held_symbols={"005930"}))
    assert signal.reason == "ALREADY_HELD_SYMBOL"


def test_no_buy_when_daily_entry_count_exceeds_limit():
    signal = _buy_signal(_snapshot(), RiskState(daily_entry_count_by_symbol={"005930": 2}))
    assert signal.reason == "MAX_DAILY_ENTRY_PER_SYMBOL_REACHED"


def test_no_buy_when_daily_loss_limit_is_reached():
    signal = _buy_signal(_snapshot(), RiskState(daily_loss_rate=-2.0))
    assert signal.reason == "DAILY_MAX_LOSS_RATE_REACHED"
