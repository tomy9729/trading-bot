from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.config.bot_config import BotConfig
from src.domain.market_data import MarketSnapshot
from src.domain.position import Position, PositionState
from src.domain.signal import Signal
from src.risk.risk_manager import RiskManager, RiskState
from src.strategy.indicators import calculate_volume_multiplier


@dataclass(frozen=True)
class FilterResult:
    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class MarketFilter:
    def __init__(self, bot_config: BotConfig):
        self.bot_config = bot_config

    def check_entry(self, market: str, snapshot: MarketSnapshot) -> FilterResult:
        """Check market-wide entry filters.

        @param market: KR or US.
        @param snapshot: Current market snapshot.
        @returns: Filter result.
        """
        if snapshot.market_direction_rate <= self.bot_config.strategy.market_down_block_threshold_percent:
            return FilterResult(False, "MARKET_DIRECTION_WEAK", {"market_direction_rate": snapshot.market_direction_rate})
        return FilterResult(True, "OK", {"market_direction_rate": snapshot.market_direction_rate, "market": market})


class SymbolFilter:
    def __init__(self, bot_config: BotConfig):
        self.bot_config = bot_config

    def check_entry(self, snapshot: MarketSnapshot) -> FilterResult:
        """Check symbol-level entry filters.

        @param snapshot: Current market snapshot.
        @returns: Filter result.
        """
        if snapshot.spread_rate > self.bot_config.strategy.max_spread_percent:
            return FilterResult(False, "SPREAD_TOO_WIDE", {"spread_rate": snapshot.spread_rate})
        if snapshot.upper_wick_rate > self.bot_config.strategy.max_upper_wick_percent:
            return FilterResult(False, "UPPER_WICK_TOO_LONG", {"upper_wick_rate": snapshot.upper_wick_rate})
        if snapshot.volume_declining:
            return FilterResult(False, "VOLUME_DECLINING", {"volume_declining": True})
        return FilterResult(True, "OK", {"spread_rate": snapshot.spread_rate, "upper_wick_rate": snapshot.upper_wick_rate})


class EntrySignal:
    def __init__(self, bot_config: BotConfig, market_filter: MarketFilter, symbol_filter: SymbolFilter):
        self.bot_config = bot_config
        self.market_filter = market_filter
        self.symbol_filter = symbol_filter

    def evaluate(
        self,
        market: str,
        snapshot: MarketSnapshot,
        position_state: PositionState,
        risk_state: RiskState,
        risk_manager: RiskManager,
    ) -> Signal:
        """Evaluate strengthened common entry conditions.

        @param market: KR or US.
        @param snapshot: Current market snapshot.
        @param position_state: Current positions.
        @param risk_state: Current risk state.
        @param risk_manager: Risk manager.
        @returns: Buy or hold signal.
        """
        details = _entry_details(snapshot)
        market_result = self.market_filter.check_entry(market, snapshot)
        details.update(market_result.details)
        if not market_result.allowed:
            return Signal("HOLD", False, market_result.reason, details)

        symbol_result = self.symbol_filter.check_entry(snapshot)
        details.update(symbol_result.details)
        if not symbol_result.allowed:
            return Signal("HOLD", False, symbol_result.reason, details)

        if snapshot.current_price <= snapshot.vwap:
            return Signal("HOLD", False, "PRICE_NOT_ABOVE_VWAP", details)
        if snapshot.vwap_hold_candle_count < self.bot_config.strategy.vwap_hold_candles:
            return Signal("HOLD", False, "VWAP_HOLD_NOT_CONFIRMED", details)

        volume_multiplier = calculate_volume_multiplier(
            snapshot.one_minute_volume,
            snapshot.previous_five_minute_average_volume,
        )
        details["volume_multiplier"] = volume_multiplier
        if volume_multiplier < self.bot_config.strategy.volume_multiplier:
            return Signal("HOLD", False, "VOLUME_SPIKE_NOT_ENOUGH", details)
        if snapshot.current_price <= snapshot.recent_high:
            return Signal("HOLD", False, "BREAKOUT_FAILED", details)
        if snapshot.execution_strength < self.bot_config.strategy.min_execution_strength:
            return Signal("HOLD", False, "EXECUTION_STRENGTH_WEAK", details)
        if snapshot.daily_rise_rate > self.bot_config.strategy.max_daily_rise_percent:
            return Signal("HOLD", False, "DAILY_RISE_RATE_TOO_HIGH", details)
        if position_state.has_symbol(snapshot.symbol):
            return Signal("HOLD", False, "ALREADY_HELD_SYMBOL", details)

        allowed, reason = risk_manager.can_enter(snapshot.symbol, risk_state)
        if not allowed:
            return Signal("HOLD", False, reason, details)
        return Signal("BUY", True, "VWAP_HOLD_VOLUME_BREAKOUT_MARKET_CONFIRMED", details)


class ExitSignal:
    def __init__(self, bot_config: BotConfig):
        self.bot_config = bot_config

    def evaluate(self, position: Position, snapshot: MarketSnapshot, now: datetime | None = None, partial_taken: bool = False) -> Signal:
        """Evaluate strengthened exit conditions.

        @param position: Open position.
        @param snapshot: Current market snapshot.
        @param now: Optional current time.
        @param partial_taken: Whether first partial profit has already run.
        @returns: Sell, partial sell, or hold signal.
        """
        current_time = now or datetime.now()
        profit_rate = ((snapshot.current_price - position.average_price) / position.average_price) * 100
        hold_minutes = (current_time - position.entry_time).total_seconds() / 60
        details = _entry_details(snapshot)
        details.update({"profit_rate": profit_rate, "hold_minutes": hold_minutes})
        if partial_taken and profit_rate <= self.bot_config.risk.break_even_stop_percent:
            return Signal("SELL", True, "BREAK_EVEN_STOP_AFTER_PARTIAL", details)
        if profit_rate <= self.bot_config.risk.stop_loss_percent:
            return Signal("SELL", True, "STOP_LOSS", details)
        if snapshot.current_price < snapshot.vwap:
            return Signal("SELL", True, "VWAP_BREAKDOWN", details)
        if hold_minutes >= self.bot_config.risk.stale_position_minutes and profit_rate < self.bot_config.risk.stale_position_min_profit_percent:
            return Signal("SELL", True, "TIME_STOP_NO_MOMENTUM", details)
        if snapshot.volume_declining:
            return Signal("SELL", True, "VOLUME_DROPPED_AFTER_BREAKOUT", details)
        if snapshot.market_direction_rate <= self.bot_config.strategy.market_down_block_threshold_percent:
            return Signal("SELL", True, "MARKET_TURNED_DOWN", details)
        if not partial_taken and profit_rate >= self.bot_config.risk.take_profit_percent:
            return Signal("PARTIAL_SELL", True, "FIRST_TAKE_PROFIT", details)
        if partial_taken and profit_rate >= self.bot_config.risk.second_take_profit_percent:
            return Signal("SELL", True, "SECOND_TAKE_PROFIT", details)
        return Signal("HOLD", False, "EXIT_CONDITION_NOT_MET", details)


def _entry_details(snapshot: MarketSnapshot) -> dict[str, Any]:
    return {
        "symbol": snapshot.symbol,
        "current_price": snapshot.current_price,
        "vwap": snapshot.vwap,
        "recent_high": snapshot.recent_high,
        "spread_rate": snapshot.spread_rate,
        "execution_strength": snapshot.execution_strength,
        "vwap_hold_candle_count": snapshot.vwap_hold_candle_count,
        "upper_wick_rate": snapshot.upper_wick_rate,
        "market_direction_rate": snapshot.market_direction_rate,
        "volume_declining": snapshot.volume_declining,
    }
