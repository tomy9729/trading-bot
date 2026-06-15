from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class MinuteCandle:
    timestamp: str
    open_price: int
    high_price: int
    low_price: int
    close_price: int
    volume: int


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    current_price: int | float
    vwap: float
    one_minute_volume: int
    previous_five_minute_average_volume: float
    recent_high: int
    daily_rise_rate: float
    trade_value: int
    spread_rate: float
    previous_candle_drop_rate: float = 0.0
    vwap_hold_candle_count: int = 0
    upper_wick_rate: float = 0.0
    execution_strength: float = 0.0
    market_direction_rate: float = 0.0
    volume_declining: bool = False
    candles: Sequence[MinuteCandle] = ()
