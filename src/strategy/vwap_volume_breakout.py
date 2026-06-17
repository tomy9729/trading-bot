from datetime import datetime

from src.config import strategy_config
from src.domain.market_data import MarketSnapshot
from src.domain.position import Position, PositionState
from src.domain.signal import Signal
from src.risk.risk_manager import RiskManager, RiskState
from src.strategy.indicators import calculate_volume_multiplier
from src.strategy.vwap_entry_rule import get_vwap_entry_threshold, is_price_above_vwap_entry_threshold


def should_buy(
    data: MarketSnapshot,
    position_state: PositionState,
    risk_state: RiskState,
    risk_manager: RiskManager,
) -> Signal:
    """Evaluate VWAP volume-breakout buy conditions.

    @param data: Current market snapshot.
    @param position_state: Current positions.
    @param risk_state: Current risk state.
    @param risk_manager: Risk manager.
    @returns: Buy or hold signal with reason and details.
    """
    details = _buy_details(data)
    vwap_entry_price_ratio = strategy_config.VWAP_ENTRY_PRICE_RATIO
    details["vwap_entry_price_ratio"] = vwap_entry_price_ratio
    details["vwap_entry_threshold"] = get_vwap_entry_threshold(data.vwap, vwap_entry_price_ratio)
    if not is_price_above_vwap_entry_threshold(data.current_price, data.vwap, vwap_entry_price_ratio):
        return Signal("HOLD", False, "PRICE_NOT_ABOVE_VWAP", details)

    volume_multiplier = calculate_volume_multiplier(
        data.one_minute_volume,
        data.previous_five_minute_average_volume,
    )
    details["volume_multiplier"] = volume_multiplier
    if volume_multiplier < strategy_config.VOLUME_SPIKE_MULTIPLIER:
        return Signal("HOLD", False, "VOLUME_SPIKE_NOT_ENOUGH", details)

    if data.previous_candle_drop_rate <= strategy_config.PREVIOUS_CANDLE_MAX_DROP_RATE:
        return Signal("HOLD", False, "PREVIOUS_CANDLE_DROP_TOO_DEEP", details)
    if data.current_price <= data.recent_high:
        return Signal("HOLD", False, "BREAKOUT_FAILED", details)
    if data.daily_rise_rate > strategy_config.MAX_RISE_RATE:
        return Signal("HOLD", False, "DAILY_RISE_RATE_TOO_HIGH", details)
    if data.trade_value < strategy_config.MIN_TRADE_VALUE:
        return Signal("HOLD", False, "TRADE_VALUE_TOO_LOW", details)
    if data.spread_rate > strategy_config.MAX_SPREAD_RATE:
        return Signal("HOLD", False, "SPREAD_RATE_TOO_HIGH", details)
    if position_state.has_symbol(data.symbol):
        return Signal("HOLD", False, "ALREADY_HELD_SYMBOL", details)

    allowed, reason = risk_manager.can_enter(data.symbol, risk_state)
    if not allowed:
        return Signal("HOLD", False, reason, details)

    return Signal("BUY", True, "VWAP_ABOVE_AND_VOLUME_BREAKOUT", details)


def should_sell(position: Position, market: MarketSnapshot, now: datetime | None = None) -> Signal:
    """Evaluate sell conditions for an open position.

    @param position: Open position.
    @param market: Current market snapshot.
    @param now: Current time, injectable for tests.
    @returns: Sell or hold signal with reason and details.
    """
    current_time = now or datetime.now()
    profit_rate = ((market.current_price - position.average_price) / position.average_price) * 100
    hold_minutes = (current_time - position.entry_time).total_seconds() / 60
    details = {
        "symbol": position.symbol,
        "current_price": market.current_price,
        "average_price": position.average_price,
        "profit_rate": profit_rate,
        "vwap": market.vwap,
        "hold_minutes": hold_minutes,
    }
    if current_time.time() >= _parse_time(strategy_config.FORCE_EXIT_TIME):
        return Signal("SELL", True, "FORCE_EXIT", details)
    if profit_rate >= strategy_config.TAKE_PROFIT_RATE:
        return Signal("SELL", True, "TAKE_PROFIT", details)
    if profit_rate <= strategy_config.STOP_LOSS_RATE:
        return Signal("SELL", True, "STOP_LOSS", details)
    if market.current_price < market.vwap:
        return Signal("SELL", True, "VWAP_BREAKDOWN", details)
    if hold_minutes >= strategy_config.MAX_HOLD_MINUTES and profit_rate < strategy_config.STALE_POSITION_MIN_PROFIT_RATE:
        return Signal("SELL", True, "TIME_EXIT", details)
    return Signal("HOLD", False, "SELL_CONDITION_NOT_MET", details)


def _buy_details(data: MarketSnapshot) -> dict:
    return {
        "symbol": data.symbol,
        "current_price": data.current_price,
        "vwap": data.vwap,
        "recent_high": data.recent_high,
        "daily_rise_rate": data.daily_rise_rate,
        "trade_value": data.trade_value,
        "spread_rate": data.spread_rate,
        "previous_candle_drop_rate": data.previous_candle_drop_rate,
    }


def _parse_time(value: str):
    hour_text, minute_text = value.split(":", 1)
    return datetime.now().replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0).time()
