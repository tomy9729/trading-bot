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
        upper_wick_details = {
            "upper_wick_rate": snapshot.upper_wick_rate,
            "max_upper_wick_percent": self.bot_config.strategy.max_upper_wick_percent,
            "upper_wick_excess_percent": max(0.0, snapshot.upper_wick_rate - self.bot_config.strategy.max_upper_wick_percent),
        }
        if snapshot.spread_rate > self.bot_config.strategy.max_spread_percent:
            return FilterResult(False, "SPREAD_TOO_WIDE", {"spread_rate": snapshot.spread_rate})
        if snapshot.upper_wick_rate > self.bot_config.strategy.max_upper_wick_percent:
            return FilterResult(False, "UPPER_WICK_TOO_LONG", upper_wick_details)
        return FilterResult(True, "OK", {"spread_rate": snapshot.spread_rate, **upper_wick_details})


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
        relaxed_conditions = []
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
        strict_vwap_hold_allowed = snapshot.vwap_hold_candle_count >= self.bot_config.strategy.vwap_hold_candles
        relaxed_vwap_hold_allowed = _is_vwap_hold_allowed(snapshot, self.bot_config)
        if not strict_vwap_hold_allowed and relaxed_vwap_hold_allowed:
            relaxed_conditions.append("VWAP_HOLD")
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
            _is_vwap_hold_allowed(snapshot, self.bot_config),
            "VWAP_HOLD_NOT_CONFIRMED",
            first_failed_reason,
        )

        volume_multiplier = calculate_volume_multiplier(
            snapshot.one_minute_volume,
            snapshot.previous_five_minute_average_volume,
        )
        details["volume_multiplier"] = volume_multiplier
        strict_volume_spike_allowed = volume_multiplier >= self.bot_config.strategy.volume_multiplier
        relaxed_volume_spike_allowed = _is_volume_spike_allowed(volume_multiplier, self.bot_config)
        if not strict_volume_spike_allowed and relaxed_volume_spike_allowed:
            relaxed_conditions.append("VOLUME_SPIKE")
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "VOLUME_SPIKE",
            _is_volume_spike_allowed(volume_multiplier, self.bot_config),
            "VOLUME_SPIKE_NOT_ENOUGH",
            first_failed_reason,
        )
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "BREAKOUT_VOLUME_SUSTAINED",
            not snapshot.volume_declining,
            "VOLUME_DECLINING",
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
        breakout_chase_rate = _rate_gap(snapshot.current_price, snapshot.recent_high)
        details["breakout_chase_rate"] = breakout_chase_rate
        details["max_breakout_chase_percent"] = self.bot_config.strategy.max_breakout_chase_percent
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "CHASE_LIMIT",
            breakout_chase_rate is None or breakout_chase_rate <= self.bot_config.strategy.max_breakout_chase_percent,
            "CHASE_PRICE_TOO_HIGH",
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

        risk_allowed, risk_reason = risk_manager.can_enter(snapshot.symbol, risk_state)
        first_failed_reason = _append_condition_result(
            matched_conditions,
            failed_conditions,
            "RISK_CHECK",
            risk_allowed,
            risk_reason,
            first_failed_reason,
        )
        details["matched_conditions"] = tuple(matched_conditions)
        details["failed_conditions"] = tuple(failed_conditions)
        details["relaxed_conditions"] = tuple(relaxed_conditions)
        details["conditional_relax_min_match_rate"] = self.bot_config.strategy.conditional_relax_min_match_rate
        details["relaxed_volume_multiplier"] = self.bot_config.strategy.relaxed_volume_multiplier
        details["relaxed_vwap_hold_candles"] = self.bot_config.strategy.relaxed_vwap_hold_candles
        if first_failed_reason is not None:
            pullback_signal = _evaluate_pullback_entry(
                snapshot,
                details,
                self.bot_config,
                market_result.allowed,
                symbol_result.allowed,
                risk_allowed,
                position_state.has_symbol(snapshot.symbol),
            )
            if pullback_signal is not None:
                return pullback_signal
            relaxed_reason = _get_conditional_relaxed_entry_reason(
                failed_conditions,
                len(matched_conditions),
                self.bot_config.strategy.conditional_relax_min_match_rate,
            )
            details["condition_match_rate"] = _condition_match_rate(matched_conditions, failed_conditions)
            if relaxed_reason is not None:
                details["conditional_relaxation_reason"] = relaxed_reason
                return Signal("BUY", True, relaxed_reason, details)
            return Signal("HOLD", False, first_failed_reason, details)
        details["condition_match_rate"] = len(matched_conditions) / (len(matched_conditions) + len(relaxed_conditions))
        if len(relaxed_conditions) > 1:
            return Signal("HOLD", False, "MULTIPLE_RELAXED_CONDITIONS", details)
        relaxed_reason = _get_relaxed_entry_reason(
            relaxed_conditions,
            len(matched_conditions),
            self.bot_config.strategy.conditional_relax_min_match_rate,
        )
        if relaxed_reason is not None:
            details["conditional_relaxation_reason"] = relaxed_reason
            return Signal("BUY", True, relaxed_reason, details)
        if self.bot_config.strategy.entry_mode == "pullback_only":
            pullback_signal = _evaluate_pullback_entry(
                snapshot,
                details,
                self.bot_config,
                market_result.allowed,
                symbol_result.allowed,
                risk_allowed,
                position_state.has_symbol(snapshot.symbol),
            )
            return pullback_signal or Signal("HOLD", False, "BREAKOUT_DISABLED_BY_ENTRY_MODE", details)
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
        volume_multiplier = calculate_volume_multiplier(
            snapshot.one_minute_volume,
            snapshot.previous_five_minute_average_volume,
        )
        profit_protection_signals = _profit_protection_signals(
            snapshot,
            volume_multiplier,
            self.bot_config.risk.profit_protection_max_execution_strength,
            self.bot_config.risk.profit_protection_min_volume_multiplier,
            self.bot_config.risk.profit_protection_upper_wick_percent,
        )
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
                "volume_multiplier": volume_multiplier,
                "hold_minutes": hold_minutes,
                "volume_drop_exit_min_hold_minutes": self.bot_config.risk.volume_drop_exit_min_hold_minutes,
                "profit_protection_min_profit_amount": self.bot_config.risk.profit_protection_min_profit_amount,
                "profit_protection_min_hold_minutes": self.bot_config.risk.profit_protection_min_hold_minutes,
                "profit_protection_weak_signal_count": self.bot_config.risk.profit_protection_weak_signal_count,
                "profit_protection_signals": tuple(profit_protection_signals),
                "profit_protection_signal_count": len(profit_protection_signals),
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
            "PULLBACK_STOP_LOSS",
            _is_pullback_stop_loss(position, snapshot, profit_rate, self.bot_config),
            first_exit_reason,
        )
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
            "EARLY_EXIT_NO_MOMENTUM",
            _is_early_exit_no_momentum(profit_rate, hold_minutes, snapshot, self.bot_config),
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "ORDERBOOK_WEAKENED",
            _is_orderbook_weakened(snapshot, self.bot_config),
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "TRAILING_PROFIT_PROTECTION",
            _is_trailing_profit_protection(position, profit_rate, snapshot, self.bot_config),
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "PROFIT_PROTECTION_EXIT",
            profit_amount > self.bot_config.risk.profit_protection_min_profit_amount
            and hold_minutes >= self.bot_config.risk.profit_protection_min_hold_minutes
            and len(profit_protection_signals) >= self.bot_config.risk.profit_protection_weak_signal_count,
            first_exit_reason,
        )
        first_exit_reason = _append_exit_condition_result(
            matched_conditions,
            failed_conditions,
            "WEAK_EXECUTION_PROFIT_PROTECTION",
            hold_minutes >= self.bot_config.risk.profit_protection_min_hold_minutes
            and _is_weak_execution_profit_protection(profit_rate, snapshot, self.bot_config),
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
            snapshot.volume_declining
            and snapshot.current_price <= snapshot.recent_high
            and trade_result.net_profit_loss > 0
            and hold_minutes >= self.bot_config.risk.volume_drop_exit_min_hold_minutes,
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
        details["exit_diagnostics"] = _exit_diagnostics(
            profit_rate,
            profit_amount,
            hold_minutes,
            snapshot,
            partial_taken,
            self.bot_config,
            profit_protection_signals,
        )
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
        "best_bid": snapshot.best_bid,
        "best_ask": snapshot.best_ask,
        "bid_quantity": snapshot.bid_quantity,
        "ask_quantity": snapshot.ask_quantity,
        "orderbook_depth_value": snapshot.orderbook_depth_value,
        "orderbook_imbalance_rate": snapshot.orderbook_imbalance_rate,
    }


def _evaluate_pullback_entry(
    snapshot: MarketSnapshot,
    base_details: dict[str, Any],
    bot_config: BotConfig,
    market_allowed: bool,
    symbol_allowed: bool,
    risk_allowed: bool,
    already_held: bool,
) -> Signal | None:
    """Evaluate pullback reentry conditions without weakening common risk filters.

    @param snapshot: Current market snapshot.
    @param base_details: Existing strategy details.
    @param bot_config: Bot configuration.
    @param market_allowed: Whether market-wide filters passed.
    @param symbol_allowed: Whether symbol filters passed.
    @param risk_allowed: Whether risk manager allowed entry.
    @param already_held: Whether the symbol is already held.
    @returns: Pullback buy signal, hold signal, or None when mode is disabled.
    """
    if bot_config.strategy.entry_mode not in {"pullback_only", "breakout_or_pullback"}:
        return None
    if not bot_config.strategy.pullback_enabled:
        return None
    details = dict(base_details)
    details["entry_mode"] = bot_config.strategy.entry_mode
    details["pullback_near_vwap_percent"] = bot_config.strategy.pullback_near_vwap_percent
    details["pullback_max_depth_percent"] = bot_config.strategy.pullback_max_depth_percent
    details["pullback_volume_cooldown_ratio"] = bot_config.strategy.pullback_volume_cooldown_ratio
    details["pullback_rebound_confirm_percent"] = bot_config.strategy.pullback_rebound_confirm_percent
    details["pullback_min_execution_strength"] = bot_config.strategy.pullback_min_execution_strength

    vwap_gap = _rate_gap(snapshot.current_price, snapshot.vwap)
    checks = {
        "COMMON_FILTERS": market_allowed and symbol_allowed and risk_allowed and not already_held,
        "NOT_CHASING_BREAKOUT": snapshot.current_price <= snapshot.recent_high,
        "NEAR_VWAP": _abs_rate_gap(snapshot.current_price, snapshot.vwap) <= bot_config.strategy.pullback_near_vwap_percent
        or (vwap_gap is not None and vwap_gap >= -bot_config.strategy.pullback_max_depth_percent),
        "PULLBACK_DEPTH_OK": _pullback_depth(snapshot) <= bot_config.strategy.pullback_max_depth_percent,
        "VOLUME_COOLDOWN": snapshot.one_minute_volume <= snapshot.previous_five_minute_average_volume * bot_config.strategy.pullback_volume_cooldown_ratio,
        "SUPPORT_NOT_BROKEN": snapshot.current_price >= snapshot.vwap * (1 - (bot_config.strategy.pullback_max_depth_percent / 100)),
        "REBOUND_CONFIRMED": _is_pullback_rebound_confirmed(snapshot, bot_config),
    }
    details["pullback_conditions"] = checks
    details["pullback_depth_percent"] = _pullback_depth(snapshot)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        details["failed_pullback_conditions"] = tuple(failed)
        return None if bot_config.strategy.entry_mode == "breakout_or_pullback" else Signal("HOLD", False, failed[0], details)
    details["entry_reason"] = "PULLBACK_REENTRY"
    details["stop_reference_price"] = min(snapshot.vwap, snapshot.current_price)
    return Signal("BUY", True, "PULLBACK_REENTRY", details)


def _pullback_depth(snapshot: MarketSnapshot) -> float:
    if snapshot.recent_high <= 0:
        return 0.0
    return max(0.0, ((snapshot.recent_high - snapshot.current_price) / snapshot.recent_high) * 100)


def _abs_rate_gap(current_price: int | float, base_price: int | float) -> float:
    value = _rate_gap(current_price, base_price)
    return abs(value) if value is not None else 0.0


def _is_pullback_rebound_confirmed(snapshot: MarketSnapshot, bot_config: BotConfig) -> bool:
    if snapshot.execution_strength >= bot_config.strategy.pullback_min_execution_strength:
        return True
    if not snapshot.candles:
        return False
    candle = snapshot.candles[-1]
    if candle.close_price < candle.open_price:
        return False
    rebound_rate = _rate_gap(snapshot.current_price, candle.low_price)
    return rebound_rate is not None and rebound_rate >= bot_config.strategy.pullback_rebound_confirm_percent


def _profit_protection_signals(
    snapshot: MarketSnapshot,
    volume_multiplier: float,
    max_execution_strength: float,
    min_volume_multiplier: float,
    upper_wick_percent: float,
) -> list[str]:
    signals = []
    if snapshot.execution_strength < max_execution_strength:
        signals.append("EXECUTION_STRENGTH_WEAK")
    if snapshot.upper_wick_rate >= upper_wick_percent:
        signals.append("UPPER_WICK_TOO_LONG")
    if volume_multiplier < min_volume_multiplier:
        signals.append("VOLUME_WEAK")
    if snapshot.market_direction_rate < 0:
        signals.append("MARKET_DIRECTION_WEAK")
    if snapshot.current_price <= snapshot.recent_high:
        signals.append("BREAKOUT_NOT_HELD")
    return signals


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


def _is_vwap_hold_allowed(snapshot: MarketSnapshot, bot_config: BotConfig) -> bool:
    """Check strict or report-driven relaxed VWAP hold thresholds.

    @param snapshot: Current market snapshot.
    @param bot_config: Bot strategy configuration.
    @returns: True when strict or relaxed VWAP hold threshold is met.
    """
    return snapshot.vwap_hold_candle_count >= bot_config.strategy.relaxed_vwap_hold_candles


def _is_volume_spike_allowed(volume_multiplier: float, bot_config: BotConfig) -> bool:
    """Check strict or report-driven relaxed volume thresholds.

    @param volume_multiplier: Current one-minute volume multiplier.
    @param bot_config: Bot strategy configuration.
    @returns: True when strict or relaxed volume threshold is met.
    """
    return volume_multiplier >= bot_config.strategy.relaxed_volume_multiplier


def _get_conditional_relaxed_entry_reason(
    failed_conditions: list[str],
    matched_count: int,
    min_match_rate: float,
) -> str | None:
    """Return a conditional relaxed entry reason for one-miss candidates.

    @param failed_conditions: Failed entry condition names.
    @param matched_count: Number of matched entry conditions.
    @param min_match_rate: Minimum condition match rate for relaxed entry.
    @returns: Relaxed entry reason, or None.
    """
    total_count = matched_count + len(failed_conditions)
    if total_count <= 0 or len(failed_conditions) != 1:
        return None
    match_rate = matched_count / total_count
    if match_rate < min_match_rate:
        return None
    failed_condition = failed_conditions[0]
    if failed_condition == "VWAP_HOLD":
        return "CONDITIONAL_RELAXED_VWAP_HOLD"
    if failed_condition == "VOLUME_SPIKE":
        return "CONDITIONAL_RELAXED_VOLUME_SPIKE"
    return None


def _get_relaxed_entry_reason(
    relaxed_conditions: list[str],
    matched_count: int,
    min_match_rate: float,
) -> str | None:
    """Return a relaxed entry reason when only one condition was relaxed.

    @param relaxed_conditions: Condition names that passed by relaxed thresholds.
    @param matched_count: Number of matched entry conditions.
    @param min_match_rate: Minimum strict condition match rate for relaxed entry.
    @returns: Relaxed entry reason, or None.
    """
    if len(relaxed_conditions) != 1:
        return None
    if matched_count / (matched_count + len(relaxed_conditions)) < min_match_rate:
        return None
    if relaxed_conditions[0] == "VWAP_HOLD":
        return "CONDITIONAL_RELAXED_VWAP_HOLD"
    if relaxed_conditions[0] == "VOLUME_SPIKE":
        return "CONDITIONAL_RELAXED_VOLUME_SPIKE"
    return None


def _condition_match_rate(matched_conditions: list[str], failed_conditions: list[str]) -> float:
    """Calculate condition match rate.

    @param matched_conditions: Matched condition names.
    @param failed_conditions: Failed condition names.
    @returns: Matched condition ratio.
    """
    total_count = len(matched_conditions) + len(failed_conditions)
    return 0.0 if total_count == 0 else len(matched_conditions) / total_count


def _exit_diagnostics(
    profit_rate: float,
    profit_amount: float,
    hold_minutes: float,
    snapshot: MarketSnapshot,
    partial_taken: bool,
    bot_config: BotConfig,
    profit_protection_signals: list[str],
) -> dict[str, Any]:
    """Create diagnostics explaining why exit conditions did or did not trigger.

    @param profit_rate: Net return rate.
    @param profit_amount: Net profit/loss amount.
    @param hold_minutes: Current hold minutes.
    @param snapshot: Current market snapshot.
    @param partial_taken: Whether first partial profit was already taken.
    @param bot_config: Bot configuration.
    @param profit_protection_signals: Current weak-profit signal names.
    @returns: Exit condition thresholds and gaps.
    """
    return {
        "stop_loss_gap_percent": profit_rate - bot_config.risk.stop_loss_percent,
        "take_profit_gap_percent": bot_config.risk.take_profit_percent - profit_rate,
        "second_take_profit_gap_percent": bot_config.risk.second_take_profit_percent - profit_rate,
        "stale_exit_minutes_left": bot_config.risk.stale_position_minutes - hold_minutes,
        "stale_min_profit_gap_percent": bot_config.risk.stale_position_min_profit_percent - profit_rate,
        "vwap_breakdown_gap": snapshot.current_price - snapshot.vwap,
        "profit_protection_amount_gap": bot_config.risk.profit_protection_min_profit_amount - profit_amount,
        "profit_protection_minutes_left": bot_config.risk.profit_protection_min_hold_minutes - hold_minutes,
        "profit_protection_signal_gap": bot_config.risk.profit_protection_weak_signal_count - len(profit_protection_signals),
        "partial_taken": partial_taken,
    }


def _is_early_exit_no_momentum(
    profit_rate: float,
    hold_minutes: float,
    snapshot: MarketSnapshot,
    bot_config: BotConfig,
) -> bool:
    """Check early failed-entry exit.

    @param profit_rate: Current net return rate.
    @param hold_minutes: Current hold minutes.
    @param snapshot: Current market snapshot.
    @param bot_config: Bot configuration.
    @returns: True when early momentum failed.
    """
    if not bot_config.risk.early_exit_enabled:
        return False
    if hold_minutes * 60 < bot_config.risk.early_exit_check_seconds:
        return False
    if profit_rate >= bot_config.risk.early_exit_min_profit_percent:
        return False
    return snapshot.execution_strength < bot_config.strategy.min_execution_strength or snapshot.current_price <= snapshot.vwap


def _is_orderbook_weakened(snapshot: MarketSnapshot, bot_config: BotConfig) -> bool:
    """Check orderbook weakening exit conditions.

    @param snapshot: Current market snapshot.
    @param bot_config: Bot configuration.
    @returns: True when orderbook risk is high enough to exit.
    """
    if not bot_config.risk.orderbook_exit_enabled:
        return False
    if snapshot.spread_rate >= bot_config.risk.orderbook_exit_max_spread_percent:
        return True
    if snapshot.orderbook_depth_value is not None and snapshot.orderbook_depth_value < bot_config.risk.orderbook_exit_min_depth_value:
        return True
    if snapshot.orderbook_imbalance_rate is not None and snapshot.orderbook_imbalance_rate <= bot_config.risk.orderbook_exit_min_imbalance_rate:
        return True
    return False


def _is_weak_execution_profit_protection(
    profit_rate: float,
    snapshot: MarketSnapshot,
    bot_config: BotConfig,
) -> bool:
    """Check profit-protection exit on weak execution strength.

    @param profit_rate: Current net return rate.
    @param snapshot: Current market snapshot.
    @param bot_config: Bot configuration.
    @returns: True when weak execution threatens an open profit.
    """
    if not bot_config.risk.weak_execution_exit_enabled:
        return False
    if profit_rate < bot_config.risk.weak_execution_exit_min_profit_percent:
        return False
    return snapshot.execution_strength <= bot_config.risk.weak_execution_exit_strength and (
        snapshot.volume_declining or snapshot.upper_wick_rate >= bot_config.strategy.max_upper_wick_percent
    )


def _is_trailing_profit_protection(
    position: Position,
    profit_rate: float,
    snapshot: MarketSnapshot,
    bot_config: BotConfig,
) -> bool:
    """Check trailing profit-protection exit.

    @param position: Open position.
    @param profit_rate: Current net return rate.
    @param snapshot: Current market snapshot.
    @param bot_config: Bot configuration.
    @returns: True when price has drawn down from the position peak.
    """
    if not bot_config.risk.trailing_exit_enabled:
        return False
    if profit_rate < bot_config.risk.trailing_start_profit_percent:
        return False
    peak_price = float(position.peak_price or position.average_price)
    if peak_price <= 0:
        return False
    drawdown_rate = ((peak_price - snapshot.current_price) / peak_price) * 100
    return drawdown_rate >= bot_config.risk.trailing_drawdown_percent


def _is_pullback_stop_loss(
    position: Position,
    snapshot: MarketSnapshot,
    profit_rate: float,
    bot_config: BotConfig,
) -> bool:
    """Check pullback-entry-specific stop loss.

    @param position: Open position.
    @param snapshot: Current market snapshot.
    @param profit_rate: Current net return rate.
    @param bot_config: Bot configuration.
    @returns: True when a pullback entry invalidates.
    """
    if position.entry_reason != "PULLBACK_REENTRY":
        return False
    stop_reference = float(position.stop_reference_price or snapshot.vwap)
    if stop_reference > 0 and snapshot.current_price < stop_reference:
        return True
    if profit_rate <= bot_config.risk.pullback_stop_loss_percent:
        return True
    vwap_gap = _rate_gap(snapshot.current_price, snapshot.vwap)
    return vwap_gap is not None and vwap_gap <= -bot_config.risk.pullback_vwap_breakdown_percent


def _rate_gap(current_price: int | float, base_price: int | float) -> float | None:
    if base_price <= 0:
        return None
    return ((current_price - base_price) / base_price) * 100
