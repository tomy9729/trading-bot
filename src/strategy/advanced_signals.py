from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.config.bot_config import BotConfig
from src.domain.market_data import MarketSnapshot
from src.domain.position import Position, PositionState
from src.risk.trading_cost import calculate_trade_cost_result
from src.domain.signal import Signal
from src.risk.risk_manager import RiskManager, RiskState
from src.strategy.indicators import calculate_volume_multiplier
from src.strategy.vwap_entry_rule import get_vwap_entry_threshold, is_price_above_vwap_entry_threshold


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

        @param market: KR.
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

        @param market: KR.
        @param snapshot: Current market snapshot.
        @param position_state: Current positions.
        @param risk_state: Current risk state.
        @param risk_manager: Risk manager.
        @returns: Buy or hold signal.
        """
        details = _entry_details(snapshot)
        matched_conditions = []
        failed_conditions = []
        first_failed_reason = None
        market_result = self.market_filter.check_entry(market, snapshot)
        details.update(market_result.details)
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "MARKET_DIRECTION",
            market_result.allowed,
            market_result.reason,
            first_failed_reason,
        )

        symbol_result = self.symbol_filter.check_entry(snapshot)
        details.update(symbol_result.details)
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "SYMBOL_FILTER",
            symbol_result.allowed,
            symbol_result.reason,
            first_failed_reason,
        )

        vwap_entry_price_ratio = self.bot_config.strategy.vwap_entry_price_ratio
        details["vwap_entry_price_ratio"] = vwap_entry_price_ratio
        details["vwap_entry_threshold"] = get_vwap_entry_threshold(snapshot.vwap, vwap_entry_price_ratio)
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "PRICE_ABOVE_VWAP",
            is_price_above_vwap_entry_threshold(snapshot.current_price, snapshot.vwap, vwap_entry_price_ratio),
            "PRICE_NOT_ABOVE_VWAP",
            first_failed_reason,
        )
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "VWAP_HOLD",
            snapshot.vwap_hold_candle_count >= self.bot_config.strategy.vwap_hold_candles,
            "VWAP_HOLD_NOT_CONFIRMED",
            first_failed_reason,
        )

        volume_multiplier = calculate_volume_multiplier(
            snapshot.one_minute_volume,
            snapshot.previous_five_minute_average_volume,
        )
        details["volume_multiplier"] = volume_multiplier
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "VOLUME_SPIKE",
            volume_multiplier >= self.bot_config.strategy.volume_multiplier,
            "VOLUME_SPIKE_NOT_ENOUGH",
            first_failed_reason,
        )
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "PRICE_BREAKOUT",
            snapshot.current_price > snapshot.recent_high,
            "BREAKOUT_FAILED",
            first_failed_reason,
        )
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "EXECUTION_STRENGTH",
            snapshot.execution_strength >= self.bot_config.strategy.min_execution_strength,
            "EXECUTION_STRENGTH_WEAK",
            first_failed_reason,
        )
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "DAILY_RISE_RATE",
            snapshot.daily_rise_rate <= self.bot_config.strategy.max_daily_rise_percent,
            "DAILY_RISE_RATE_TOO_HIGH",
            first_failed_reason,
        )
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "NOT_ALREADY_HELD",
            not position_state.has_symbol(snapshot.symbol),
            "ALREADY_HELD_SYMBOL",
            first_failed_reason,
        )

        allowed, reason = risk_manager.can_enter(snapshot.symbol, risk_state)
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "RISK_CHECK",
            allowed,
            reason,
            first_failed_reason,
        )
        details["matched_conditions"] = tuple(matched_conditions)
        details["failed_conditions"] = tuple(failed_conditions)
        if first_failed_reason is not None:
            return Signal("HOLD", False, first_failed_reason, details)
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
        cost = self.bot_config.cost
        trade_result = calculate_trade_cost_result(
            position.average_price,
            snapshot.current_price,
            position.quantity,
            buy_fee_percent=cost.buy_fee_percent,
            sell_fee_percent=cost.sell_fee_percent,
            sell_tax_percent=cost.sell_tax_percent,
            sell_slippage_percent=cost.slippage_percent,
        )
        profit_rate = trade_result.net_return_rate
        profit_amount = trade_result.net_profit_loss
        hold_minutes = (current_time - position.entry_time).total_seconds() / 60
        details = _entry_details(snapshot)
        details.update(
            {
                "entry_price": position.average_price,
                "average_price": position.average_price,
                "position_quantity": position.quantity,
                "profit_rate": profit_rate,
                "profit_amount": profit_amount,
                "gross_profit_rate": trade_result.gross_return_rate,
                "gross_profit_amount": trade_result.gross_profit_loss,
                "net_profit_rate": trade_result.net_return_rate,
                "net_profit_amount": trade_result.net_profit_loss,
                "estimated_buy_fee": trade_result.buy_fee,
                "estimated_sell_fee": trade_result.sell_fee,
                "estimated_sell_tax": trade_result.sell_tax,
                "estimated_slippage_cost": trade_result.slippage_cost,
                "estimated_total_cost": trade_result.total_cost,
                "hold_minutes": hold_minutes,
                "stop_loss_price": position.average_price * (1 + (self.bot_config.risk.stop_loss_percent / 100)),
                "take_profit_price": position.average_price * (1 + (self.bot_config.risk.take_profit_percent / 100)),
            }
        )
        matched_conditions = []
        failed_conditions = []
        first_exit_reason = None
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "BREAK_EVEN_STOP_AFTER_PARTIAL",
            partial_taken and profit_rate <= self.bot_config.risk.break_even_stop_percent,
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "STOP_LOSS",
            profit_rate <= self.bot_config.risk.stop_loss_percent,
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "VWAP_BREAKDOWN",
            snapshot.current_price < snapshot.vwap,
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "TIME_STOP_NO_MOMENTUM",
            hold_minutes >= self.bot_config.risk.stale_position_minutes and profit_rate < self.bot_config.risk.stale_position_min_profit_percent,
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "VOLUME_DROPPED_AFTER_BREAKOUT",
            snapshot.volume_declining and trade_result.net_profit_loss > 0,
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "MARKET_TURNED_DOWN",
            snapshot.market_direction_rate <= self.bot_config.strategy.market_down_block_threshold_percent,
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "FIRST_TAKE_PROFIT",
            not partial_taken and profit_rate >= self.bot_config.risk.take_profit_percent,
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "SECOND_TAKE_PROFIT",
            partial_taken and profit_rate >= self.bot_config.risk.second_take_profit_percent,
            first_exit_reason,
        )
        details["matched_conditions"] = tuple(matched_conditions)
        details["failed_conditions"] = tuple(failed_conditions)
        if first_exit_reason is not None:
            return Signal("PARTIAL_SELL" if first_exit_reason == "FIRST_TAKE_PROFIT" else "SELL", True, first_exit_reason, details)
        return Signal("HOLD", False, "EXIT_CONDITION_NOT_MET", details)


def _entry_details(snapshot: MarketSnapshot) -> dict[str, Any]:
    return {
        "symbol": snapshot.symbol,
        "current_price": snapshot.current_price,
        "vwap": snapshot.vwap,
        "vwap_gap": _rate_gap(snapshot.current_price, snapshot.vwap),
        "one_minute_volume": snapshot.one_minute_volume,
        "previous_five_minute_average_volume": snapshot.previous_five_minute_average_volume,
        "recent_high": snapshot.recent_high,
        "daily_rise_rate": snapshot.daily_rise_rate,
        "trade_value": snapshot.trade_value,
        "spread_rate": snapshot.spread_rate,
        "previous_candle_drop_rate": snapshot.previous_candle_drop_rate,
        "execution_strength": snapshot.execution_strength,
        "vwap_hold_candle_count": snapshot.vwap_hold_candle_count,
        "upper_wick_rate": snapshot.upper_wick_rate,
        "market_direction_rate": snapshot.market_direction_rate,
        "volume_declining": snapshot.volume_declining,
    }


def _append_condition_result(
    matched_conditions: list[str],
    failed_conditions: list[str],
    name: str,
    allowed: bool,
    failed_reason: str,
    first_failed_reason: str | None,
) -> str | None:
    if allowed:
        matched_conditions.append(name)
        return first_failed_reason
    failed_conditions.append(name)
    return first_failed_reason or failed_reason


def _append_exit_condition_result(
    matched_conditions: list[str],
    failed_conditions: list[str],
    reason: str,
    matched: bool,
    first_exit_reason: str | None,
) -> str | None:
    if matched:
        matched_conditions.append(reason)
        return first_exit_reason or reason
    failed_conditions.append(reason)
    return first_exit_reason


def _rate_gap(current_price: int | float, base_price: int | float) -> float | None:
    if base_price <= 0:
        return None
    return ((current_price - base_price) / base_price) * 100
