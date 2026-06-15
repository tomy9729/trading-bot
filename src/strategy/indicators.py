from typing import Sequence

from src.domain.market_data import MinuteCandle


def calculate_vwap(candles: Sequence[MinuteCandle]) -> float:
    """Calculate VWAP from minute candles.

    @param candles: Minute candles.
    @returns: VWAP value, or 0.0 when volume is empty.
    """
    total_volume = sum(candle.volume for candle in candles)
    if total_volume <= 0:
        return 0.0
    total_value = sum(_typical_price(candle) * candle.volume for candle in candles)
    return total_value / total_volume


def calculate_volume_multiplier(current_volume: int, average_volume: float) -> float:
    """Calculate current volume relative to previous average volume.

    @param current_volume: Current one-minute volume.
    @param average_volume: Previous average volume.
    @returns: Volume multiplier.
    """
    if average_volume <= 0:
        return 0.0
    return current_volume / average_volume


def _typical_price(candle: MinuteCandle) -> float:
    return (candle.high_price + candle.low_price + candle.close_price) / 3
