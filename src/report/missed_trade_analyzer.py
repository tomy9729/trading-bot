from dataclasses import dataclass
from typing import Any

from src.config.bot_config import BotConfig
from src.report.report_parser import ReportEvent
from src.report.simulated_trade_calculator import SimulatedTradeResult, calculate_simulated_trade
from src.strategy.vwap_entry_rule import get_vwap_entry_threshold


ENTRY_CONDITIONS = (
    "시장 방향",
    "스프레드",
    "윗꼬리",
    "거래량 감소 아님",
    "VWAP 상단",
    "VWAP 유지",
    "거래량 급증",
    "박스권 돌파",
    "체결강도",
)


@dataclass(frozen=True)
class MissedTradeCandidate:
    detected_at: str
    symbol: str
    name: str
    price: float | None
    later_high: float | None
    later_low: float | None
    reason: str
    satisfied_conditions: tuple[str, ...]
    failed_conditions: tuple[str, ...]
    condition_match_rate: float | None
    simulation: SimulatedTradeResult
    adjustment: str


def analyze_missed_candidates(events: list[ReportEvent], bot_config: BotConfig) -> list[MissedTradeCandidate]:
    """Analyze buy candidates that were not actually bought.

    @param events: Parsed report events.
    @param bot_config: Trading bot config.
    @returns: Missed buy candidate analysis.
    """
    buy_checks = [event for event in events if event.event_type == "BUY_CONDITION_CHECKED"]
    buy_fills = [event for event in events if event.event_type == "BUY_ORDER_FILLED"]
    candidates = []
    for event in buy_checks:
        details = _details(event)
        symbol = str(details.get("symbol") or event.data.get("symbol") or "")
        if not symbol:
            continue
        if event.data.get("allowed") is True and _has_later_buy_fill(symbol, event, buy_fills):
            continue
        price = _to_float(details.get("current_price"))
        satisfied, failed = _evaluate_conditions(details, str(event.data.get("reason") or ""), bot_config)
        if not _is_missed_candidate(satisfied, failed, str(event.data.get("reason") or ""), event.data.get("allowed") is True):
            continue
        later_prices = [
            _to_float(_details(later_event).get("current_price"))
            for later_event in buy_checks
            if later_event.timestamp > event.timestamp and str(_details(later_event).get("symbol") or later_event.data.get("symbol") or "") == symbol
        ]
        later_prices = [value for value in later_prices if value is not None]
        quantity = 1
        simulation = calculate_simulated_trade(
            price,
            min(later_prices) if later_prices else None,
            later_prices[-1] if later_prices else None,
            max(later_prices) if later_prices else None,
            quantity,
            buy_fee_percent=bot_config.cost.buy_fee_percent,
            sell_fee_percent=bot_config.cost.sell_fee_percent,
            sell_tax_percent=bot_config.cost.sell_tax_percent,
            sell_slippage_percent=bot_config.cost.slippage_percent,
        )
        candidates.append(
            MissedTradeCandidate(
                detected_at=event.timestamp.strftime("%H:%M:%S"),
                symbol=symbol,
                name=_event_name(event),
                price=price,
                later_high=max(later_prices) if later_prices else None,
                later_low=min(later_prices) if later_prices else None,
                reason=str(event.data.get("reason") or "분석 불가"),
                satisfied_conditions=tuple(satisfied),
                failed_conditions=tuple(failed),
                condition_match_rate=(len(satisfied) / len(ENTRY_CONDITIONS)) * 100 if ENTRY_CONDITIONS else None,
                simulation=simulation,
                adjustment=_create_adjustment_text(details, str(event.data.get("reason") or ""), bot_config),
            )
        )
    return sorted(candidates, key=_candidate_sort_key, reverse=True)[:20]


def _is_missed_candidate(satisfied: list[str], failed: list[str], reason: str, allowed: bool) -> bool:
    if allowed:
        return True
    candidate_reasons = {
        "VOLUME_SPIKE_NOT_ENOUGH",
        "VWAP_HOLD_NOT_CONFIRMED",
        "BREAKOUT_FAILED",
        "EXECUTION_STRENGTH_WEAK",
        "NO_ORDER_QUANTITY",
        "MAX_POSITION_COUNT_REACHED",
        "SPREAD_TOO_WIDE",
        "NEW_BUY_TIME_BLOCKED",
        "MARKET_DIRECTION_WEAK",
        "UPPER_WICK_TOO_LONG",
    }
    return reason in candidate_reasons or (len(satisfied) >= 4 and len(failed) > 0)


def _has_later_buy_fill(symbol: str, event: ReportEvent, buy_fills: list[ReportEvent]) -> bool:
    """Check whether a buy signal has a later actual fill.

    @param symbol: Candidate symbol.
    @param event: Buy signal event.
    @param buy_fills: Parsed buy fill events.
    @returns: True when a later buy fill exists for the same symbol.
    """
    for buy_fill in buy_fills:
        fill_symbol = str(buy_fill.data.get("symbol") or "")
        if fill_symbol == symbol and buy_fill.timestamp >= event.timestamp:
            return True
    return False


def _evaluate_conditions(details: dict[str, Any], reason: str, bot_config: BotConfig) -> tuple[list[str], list[str]]:
    satisfied = []
    failed = []
    _append_condition(satisfied, failed, "시장 방향", _to_float(details.get("market_direction_rate"), 0.0) > bot_config.strategy.market_down_block_threshold_percent)
    _append_condition(satisfied, failed, "스프레드", _to_float(details.get("spread_rate"), 999.0) <= bot_config.strategy.max_spread_percent)
    _append_condition(satisfied, failed, "윗꼬리", _to_float(details.get("upper_wick_rate"), 999.0) <= bot_config.strategy.max_upper_wick_percent)
    _append_condition(satisfied, failed, "거래량 감소 아님", details.get("volume_declining") is not True)
    vwap = _to_float(details.get("vwap"), 999999999.0)
    threshold = get_vwap_entry_threshold(vwap, bot_config.strategy.vwap_entry_price_ratio)
    _append_condition(satisfied, failed, "VWAP 상단", _to_float(details.get("current_price"), 0.0) > threshold)
    _append_condition(satisfied, failed, "VWAP 유지", _to_float(details.get("vwap_hold_candle_count"), 0.0) >= bot_config.strategy.vwap_hold_candles)
    if "volume_multiplier" in details:
        _append_condition(satisfied, failed, "거래량 급증", _to_float(details.get("volume_multiplier"), 0.0) >= bot_config.strategy.volume_multiplier)
    elif reason == "VOLUME_SPIKE_NOT_ENOUGH":
        failed.append("거래량 급증")
    else:
        failed.append("거래량 급증")
    _append_condition(satisfied, failed, "박스권 돌파", _to_float(details.get("current_price"), 0.0) > _to_float(details.get("recent_high"), 999999999.0))
    _append_condition(satisfied, failed, "체결강도", _to_float(details.get("execution_strength"), 0.0) >= bot_config.strategy.min_execution_strength)
    return satisfied, failed


def _create_adjustment_text(details: dict[str, Any], reason: str, bot_config: BotConfig) -> str:
    if reason == "VOLUME_SPIKE_NOT_ENOUGH":
        actual = _to_float(details.get("volume_multiplier"))
        return f"거래량 기준을 {actual:.2f}배 이하로 완화하면 매수 가능" if actual is not None else "거래량 기준 완화 필요 여부 분석 불가"
    if reason == "VWAP_HOLD_NOT_CONFIRMED":
        actual = _to_float(details.get("vwap_hold_candle_count"))
        return f"VWAP 유지 기준을 {int(actual)}개 이하로 완화하면 매수 가능" if actual is not None else "VWAP 유지 기준 완화 필요 여부 분석 불가"
    if reason == "SPREAD_TOO_WIDE":
        actual = _to_float(details.get("spread_rate"))
        return f"스프레드 기준을 {actual:.4f}% 이상으로 완화하면 매수 가능" if actual is not None else "스프레드 기준 완화 필요 여부 분석 불가"
    if reason == "UPPER_WICK_TOO_LONG":
        actual = _to_float(details.get("upper_wick_rate"))
        return f"윗꼬리 기준을 {actual:.2f}% 이상으로 완화하면 매수 가능" if actual is not None else "윗꼬리 기준 완화 필요 여부 분석 불가"
    if reason == "EXECUTION_STRENGTH_WEAK":
        actual = _to_float(details.get("execution_strength"))
        return f"체결강도 기준을 {actual:.2f} 이하로 완화하면 매수 가능" if actual is not None else "체결강도 기준 완화 필요 여부 분석 불가"
    if reason == "BREAKOUT_FAILED":
        price = _to_float(details.get("current_price"))
        recent_high = _to_float(details.get("recent_high"))
        if price is None or recent_high is None:
            return "돌파 기준 완화 필요 여부 분석 불가"
        return f"돌파 기준을 직전 고점 {recent_high:g} 이하 또는 현재가 {price:g} 기준으로 완화하면 매수 가능"
    if reason == "NEW_BUY_TIME_BLOCKED":
        return "신규 진입 허용 시간대를 확대하면 매수 가능"
    if reason == "MAX_POSITION_COUNT_REACHED":
        return f"최대 보유 종목 수를 {bot_config.risk.max_position_count + 1}개 이상으로 완화하면 매수 가능"
    if reason == "NO_ORDER_QUANTITY":
        return "주문 가능 예산 또는 1회 매수 한도를 늘리면 매수 가능"
    return "분석 불가"


def _append_condition(satisfied: list[str], failed: list[str], name: str, allowed: bool) -> None:
    if allowed:
        satisfied.append(name)
    else:
        failed.append(name)


def _details(event: ReportEvent) -> dict[str, Any]:
    details = event.data.get("details")
    return details if isinstance(details, dict) else {}


def _event_name(event: ReportEvent) -> str:
    value = event.data.get("name")
    if value not in (None, "", "None"):
        return str(value)
    return "분석 불가"


def _candidate_sort_key(candidate: MissedTradeCandidate) -> tuple[float, float]:
    match_rate = candidate.condition_match_rate if candidate.condition_match_rate is not None else 0.0
    expected_rate = candidate.simulation.neutral_return_rate if candidate.simulation.neutral_return_rate is not None else 0.0
    return match_rate, expected_rate


def _to_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
