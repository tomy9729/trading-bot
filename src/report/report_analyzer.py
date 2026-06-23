from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.config.bot_config import TradingCostConfig
from src.report.report_parser import ReportEvent
from src.risk.trading_cost import calculate_trade_cost_result


@dataclass(frozen=True)
class TradeRecord:
    time: str
    symbol: str
    name: str
    side: str
    price: float | None
    quantity: float | None
    amount: float | None
    gross_profit_loss: float | None
    total_cost: float | None
    return_rate: float | None
    profit_loss: float | None
    reason: str


@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    name: str
    buy_time: str
    buy_price: float | None
    sell_time: str
    sell_price: float | None
    hold_minutes: float | None
    gross_profit_loss: float | None
    total_cost: float | None
    return_rate: float | None
    profit_loss: float | None
    buy_reason: str
    sell_reason: str


@dataclass(frozen=True)
class TradeSummary:
    total_buy_count: int
    total_sell_count: int
    total_symbol_count: int
    total_realized_profit_loss: float | None
    total_return_rate: float | None
    win_rate: float | None
    average_return_rate: float | None
    average_loss_rate: float | None
    best_trade: str
    worst_trade: str
    average_hold_minutes: float | None


@dataclass(frozen=True)
class ReportAnalysis:
    summary: TradeSummary
    trade_records: list[TradeRecord] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    condition_counts: dict[str, int] = field(default_factory=dict)
    reject_counts: dict[str, int] = field(default_factory=dict)


def analyze_trades(events: list[ReportEvent], cost_config: TradingCostConfig | None = None) -> ReportAnalysis:
    """Analyze actual buy and sell results from parsed events.

    @param events: Parsed report events.
    @returns: Actual trade analysis.
    """
    records = []
    closed_trades = []
    open_by_symbol: dict[str, TradeRecord] = {}
    last_buy_signal_by_symbol: dict[str, ReportEvent] = {}
    last_sell_signal_by_symbol: dict[str, ReportEvent] = {}
    condition_counts: dict[str, int] = {}
    reject_counts: dict[str, int] = {}

    for event in events:
        if event.event_type == "BUY_CONDITION_CHECKED":
            reason = str(event.data.get("reason") or "분석 불가")
            condition_counts[reason] = condition_counts.get(reason, 0) + 1
            symbol = _symbol(event)
            if event.data.get("allowed") is True and symbol:
                last_buy_signal_by_symbol[symbol] = event
            elif symbol:
                reject_counts[reason] = reject_counts.get(reason, 0) + 1
        elif event.event_type == "SELL_CONDITION_CHECKED":
            symbol = _symbol(event)
            if symbol:
                last_sell_signal_by_symbol[symbol] = event
        elif event.event_type == "BUY_ORDER_FILLED":
            record = _create_buy_record(event, last_buy_signal_by_symbol.get(str(event.data.get("symbol") or "")))
            records.append(record)
            open_by_symbol[record.symbol] = record
        elif event.event_type == "SELL_ORDER_FILLED":
            record = _create_sell_record(
                event,
                open_by_symbol.get(str(event.data.get("symbol") or "")),
                last_sell_signal_by_symbol.get(str(event.data.get("symbol") or "")),
                cost_config,
            )
            records.append(record)
            buy_record = open_by_symbol.pop(record.symbol, None)
            closed_trades.append(_create_closed_trade(buy_record, record, last_sell_signal_by_symbol.get(record.symbol)))

    summary = _create_summary(records, closed_trades)
    return ReportAnalysis(summary=summary, trade_records=records, closed_trades=closed_trades, condition_counts=condition_counts, reject_counts=reject_counts)


def _create_buy_record(event: ReportEvent, signal_event: ReportEvent | None) -> TradeRecord:
    price = _to_float(event.data.get("entry_price"))
    quantity = _to_float(event.data.get("quantity"))
    reason = str(signal_event.data.get("reason")) if signal_event is not None else "분석 불가"
    return TradeRecord(
        time=event.timestamp.strftime("%H:%M:%S"),
        symbol=str(event.data.get("symbol") or ""),
        name=_event_name(event, signal_event),
        side="매수",
        price=price,
        quantity=quantity,
        amount=_amount(price, quantity),
        gross_profit_loss=None,
        total_cost=None,
        return_rate=None,
        profit_loss=None,
        reason=reason,
    )


def _create_sell_record(
    event: ReportEvent,
    buy_record: TradeRecord | None,
    signal_event: ReportEvent | None,
    cost_config: TradingCostConfig | None,
) -> TradeRecord:
    signal_details = _details(signal_event)
    price = _to_float(event.data.get("exit_price"))
    if price is None:
        price = _to_float(signal_details.get("current_price"))
    quantity = _to_float(event.data.get("quantity"))
    return_rate = _to_float(signal_details.get("profit_rate"))
    profit_loss = None
    gross_profit_loss = None
    total_cost = None
    if price is not None and quantity is not None and buy_record is not None and buy_record.price is not None:
        if cost_config is None:
            profit_loss = (price - buy_record.price) * quantity
            gross_profit_loss = profit_loss
            total_cost = 0.0
            return_rate = ((price - buy_record.price) / buy_record.price) * 100
        else:
            result = calculate_trade_cost_result(
                buy_record.price,
                price,
                quantity,
                buy_fee_percent=cost_config.buy_fee_percent,
                sell_fee_percent=cost_config.sell_fee_percent,
                sell_tax_percent=cost_config.sell_tax_percent,
            )
            gross_profit_loss = result.gross_profit_loss
            total_cost = result.total_cost
            profit_loss = result.net_profit_loss
            return_rate = result.net_return_rate
    elif price is not None and quantity is not None and return_rate is not None:
        entry_price = price / (1 + (return_rate / 100))
        profit_loss = (price - entry_price) * quantity
    return TradeRecord(
        time=event.timestamp.strftime("%H:%M:%S"),
        symbol=str(event.data.get("symbol") or ""),
        name=_event_name(event, signal_event),
        side="매도",
        price=price,
        quantity=quantity,
        amount=_amount(price, quantity),
        gross_profit_loss=gross_profit_loss,
        total_cost=total_cost,
        return_rate=return_rate,
        profit_loss=profit_loss,
        reason=str(event.data.get("reason") or (signal_event.data.get("reason") if signal_event is not None else "분석 불가")),
    )


def _create_closed_trade(buy_record: TradeRecord | None, sell_record: TradeRecord, signal_event: ReportEvent | None) -> ClosedTrade:
    hold_minutes = _to_float(_details(signal_event).get("hold_minutes"))
    return ClosedTrade(
        symbol=sell_record.symbol,
        name=sell_record.name,
        buy_time=buy_record.time if buy_record is not None else "분석 불가",
        buy_price=buy_record.price if buy_record is not None else None,
        sell_time=sell_record.time,
        sell_price=sell_record.price,
        hold_minutes=hold_minutes,
        gross_profit_loss=sell_record.gross_profit_loss,
        total_cost=sell_record.total_cost,
        return_rate=sell_record.return_rate,
        profit_loss=sell_record.profit_loss,
        buy_reason=buy_record.reason if buy_record is not None else "분석 불가",
        sell_reason=sell_record.reason,
    )


def _create_summary(records: list[TradeRecord], closed_trades: list[ClosedTrade]) -> TradeSummary:
    buys = [record for record in records if record.side == "매수"]
    sells = [record for record in records if record.side == "매도"]
    symbols = {record.symbol for record in records if record.symbol}
    realized_values = [trade.profit_loss for trade in closed_trades if trade.profit_loss is not None]
    return_rates = [trade.return_rate for trade in closed_trades if trade.return_rate is not None]
    wins = [rate for rate in return_rates if rate > 0]
    losses = [rate for rate in return_rates if rate < 0]
    hold_values = [trade.hold_minutes for trade in closed_trades if trade.hold_minutes is not None]
    total_buy_amount = sum(record.amount or 0 for record in buys)
    total_profit_loss = sum(realized_values) if realized_values else None
    best_trade = _format_extreme_trade(closed_trades, max) if return_rates else "분석 불가"
    worst_trade = _format_extreme_trade(closed_trades, min) if return_rates else "분석 불가"
    return TradeSummary(
        total_buy_count=len(buys),
        total_sell_count=len(sells),
        total_symbol_count=len(symbols),
        total_realized_profit_loss=total_profit_loss,
        total_return_rate=(total_profit_loss / total_buy_amount * 100) if total_profit_loss is not None and total_buy_amount > 0 else None,
        win_rate=(len(wins) / len(return_rates) * 100) if return_rates else None,
        average_return_rate=(sum(wins) / len(wins)) if wins else None,
        average_loss_rate=(sum(losses) / len(losses)) if losses else None,
        best_trade=best_trade,
        worst_trade=worst_trade,
        average_hold_minutes=(sum(hold_values) / len(hold_values)) if hold_values else None,
    )


def _format_extreme_trade(closed_trades: list[ClosedTrade], selector) -> str:
    trades = [trade for trade in closed_trades if trade.return_rate is not None]
    if not trades:
        return "분석 불가"
    selected = selector(trades, key=lambda trade: trade.return_rate or 0)
    return f"{selected.symbol} {selected.return_rate:.2f}%"


def _symbol(event: ReportEvent) -> str:
    return str(_details(event).get("symbol") or event.data.get("symbol") or "")


def _event_name(event: ReportEvent, fallback_event: ReportEvent | None = None) -> str:
    value = event.data.get("name") or (fallback_event.data.get("name") if fallback_event is not None else None)
    if value not in (None, "", "None"):
        return str(value)
    return "분석 불가"


def _details(event: ReportEvent | None) -> dict[str, Any]:
    if event is None:
        return {}
    details = event.data.get("details")
    return details if isinstance(details, dict) else {}


def _amount(price: float | None, quantity: float | None) -> float | None:
    if price is None or quantity is None:
        return None
    return price * quantity


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
