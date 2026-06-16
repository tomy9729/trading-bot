from datetime import datetime
from typing import Any, Sequence

from src.config.bot_config import StrategyConfig
from src.domain.market_data import MarketSnapshot, MinuteCandle
from src.strategy.indicators import calculate_vwap


class MarketSnapshotBuilder:
    def __init__(self, strategy_config: StrategyConfig):
        self.strategy_config = strategy_config

    def build(self, symbol: str, candles: Sequence[MinuteCandle], current_price: int | float, spread_rate: float, daily_rise_rate: float = 0.0) -> MarketSnapshot:
        """Build a strategy snapshot from minute candles and quote data.

        @param symbol: Stock symbol.
        @param candles: Minute candles, newest first or oldest first.
        @param current_price: Current price.
        @param spread_rate: Current spread rate.
        @param daily_rise_rate: Daily rise rate.
        @returns: Market snapshot used by strategy functions.
        """
        ordered_candles = _sort_candles(candles)
        if len(ordered_candles) < self.strategy_config.breakout_window_minutes + 1:
            raise ValueError("not enough candles to build market snapshot")

        last_candle = ordered_candles[-1]
        previous_window = ordered_candles[-(self.strategy_config.breakout_window_minutes + 1):-1]
        volume_window = ordered_candles[-(self.strategy_config.volume_lookback_minutes + 1):-1]
        previous_volumes = [candle.volume for candle in previous_window]
        average_volume = sum(candle.volume for candle in volume_window) / len(volume_window)
        recent_high = max(candle.high_price for candle in previous_window)
        previous_candle = ordered_candles[-2]
        previous_drop_rate = _drop_rate(previous_candle)
        trade_value = int(sum(candle.close_price * candle.volume for candle in ordered_candles[-30:]))
        vwap = calculate_vwap(ordered_candles)
        return MarketSnapshot(
            symbol=symbol,
            current_price=current_price,
            vwap=vwap,
            one_minute_volume=last_candle.volume,
            previous_five_minute_average_volume=average_volume,
            recent_high=recent_high,
            daily_rise_rate=daily_rise_rate,
            trade_value=trade_value,
            spread_rate=spread_rate,
            previous_candle_drop_rate=previous_drop_rate,
            vwap_hold_candle_count=_vwap_hold_count(ordered_candles, vwap),
            upper_wick_rate=_upper_wick_rate(last_candle),
            execution_strength=_execution_strength(last_candle),
            market_direction_rate=_market_direction_rate(ordered_candles),
            volume_declining=_is_volume_declining(ordered_candles),
            candles=tuple(ordered_candles),
        )


def parse_domestic_candles(rows: Sequence[dict[str, Any]]) -> list[MinuteCandle]:
    """Parse KIS domestic minute candle rows.

    @param rows: KIS output2 rows.
    @returns: Parsed minute candles.
    """
    candles = []
    for row in rows:
        timestamp = f"{row.get('stck_bsop_date', '')}{row.get('stck_cntg_hour', row.get('cntg_hour', ''))}"
        candles.append(
            MinuteCandle(
                timestamp=timestamp,
                open_price=_to_int(row, ("stck_oprc", "oprc", "open")),
                high_price=_to_int(row, ("stck_hgpr", "hgpr", "high")),
                low_price=_to_int(row, ("stck_lwpr", "lwpr", "low")),
                close_price=_to_int(row, ("stck_prpr", "prpr", "last", "close")),
                volume=_to_int(row, ("cntg_vol", "acml_vol", "volume", "vol")),
            )
        )
    return candles


def _sort_candles(candles: Sequence[MinuteCandle]) -> list[MinuteCandle]:
    return sorted(candles, key=lambda candle: candle.timestamp)


def _drop_rate(candle: MinuteCandle) -> float:
    if candle.open_price <= 0:
        return 0.0
    return ((candle.close_price - candle.open_price) / candle.open_price) * 100


def _vwap_hold_count(candles: Sequence[MinuteCandle], vwap: float) -> int:
    count = 0
    for candle in reversed(candles):
        if candle.close_price <= vwap:
            break
        count += 1
    return count


def _upper_wick_rate(candle: MinuteCandle) -> float:
    candle_range = candle.high_price - candle.low_price
    if candle_range <= 0:
        return 0.0
    upper_wick = candle.high_price - max(candle.open_price, candle.close_price)
    return (upper_wick / candle_range) * 100


def _execution_strength(candle: MinuteCandle) -> float:
    candle_range = candle.high_price - candle.low_price
    if candle_range <= 0:
        return 50.0
    close_position = ((candle.close_price - candle.low_price) / candle_range) * 100
    if candle.close_price >= candle.open_price:
        return min(100.0, close_position + 10.0)
    return max(0.0, close_position - 10.0)


def _market_direction_rate(candles: Sequence[MinuteCandle]) -> float:
    if len(candles) < 5:
        return 0.0
    first = candles[-5].close_price
    last = candles[-1].close_price
    if first <= 0:
        return 0.0
    return ((last - first) / first) * 100


def _is_volume_declining(candles: Sequence[MinuteCandle]) -> bool:
    if len(candles) < 3:
        return False
    return candles[-1].volume < candles[-2].volume < candles[-3].volume


def _to_int(row: dict[str, Any], names: tuple[str, ...]) -> int:
    return int(_to_float(row, names))


def _to_float(row: dict[str, Any], names: tuple[str, ...]) -> float:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return float(str(value).replace(",", ""))
    raise ValueError(f"missing numeric field candidates={names}, row={row}")
