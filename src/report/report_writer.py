from pathlib import Path
from typing import Any

from src.report.missed_trade_analyzer import MissedTradeCandidate
from src.report.report_analyzer import ReportAnalysis


ANALYSIS_UNAVAILABLE = "분석 불가"


def get_default_report_path(report_date: str) -> Path:
    """Create the default daily report path.

    @param report_date: Normalized YYYY-MM-DD date.
    @returns: reports/YYYY-MM-DD-daily-trading-report.md path.
    """
    return Path("reports") / f"{report_date}-daily-trading-report.md"


def write_report(report_date: str, analysis: ReportAnalysis, missed_candidates: list[MissedTradeCandidate], save: bool) -> Path | None:
    """Create a daily trading report and optionally save it.

    @param report_date: Normalized YYYY-MM-DD date.
    @param analysis: Actual trade analysis.
    @param missed_candidates: Missed candidate analysis.
    @param save: Whether to save the report file.
    @returns: Saved report path, or None when save is false.
    """
    content = create_report_markdown(report_date, analysis, missed_candidates)
    if not save:
        print(content)
        return None
    report_path = get_default_report_path(report_date)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
    return report_path


def create_report_markdown(report_date: str, analysis: ReportAnalysis, missed_candidates: list[MissedTradeCandidate]) -> str:
    """Create Markdown content for a daily trading report.

    @param report_date: Normalized YYYY-MM-DD date.
    @param analysis: Actual trade analysis.
    @param missed_candidates: Missed candidate analysis.
    @returns: Markdown report content.
    """
    lines = [
        f"# Daily Trading Report - {report_date}",
        "",
        "## 1. 당일 요약",
        "",
        f"- 총 매수 횟수: {analysis.summary.total_buy_count}",
        f"- 총 매도 횟수: {analysis.summary.total_sell_count}",
        f"- 총 거래 종목 수: {analysis.summary.total_symbol_count}",
        f"- 총 실현 손익: {_format_money(analysis.summary.total_realized_profit_loss)}",
        f"- 총 수익률: {_format_percent(analysis.summary.total_return_rate)}",
        f"- 승률: {_format_percent(analysis.summary.win_rate)}",
        f"- 평균 수익률: {_format_percent(analysis.summary.average_return_rate)}",
        f"- 평균 손실률: {_format_percent(analysis.summary.average_loss_rate)}",
        f"- 최대 수익 거래: {analysis.summary.best_trade}",
        f"- 최대 손실 거래: {analysis.summary.worst_trade}",
        f"- 평균 보유 시간: {_format_minutes(analysis.summary.average_hold_minutes)}",
        "",
        "## 2. 실제 매수/매도 기록",
        "",
        _trade_records_table(analysis),
        "",
        "## 3. 종목별 상세 결과",
        "",
        _closed_trades_table(analysis),
        "",
        "## 4. 매수될 뻔한 후보 분석",
        "",
        _missed_candidates_table(missed_candidates),
        "",
        "## 5. 전략 개선 분석",
        "",
        _strategy_analysis(analysis),
        "",
        "## 6. 놓친 기회 분석",
        "",
        _missed_opportunity_analysis(missed_candidates),
        "",
        "## 7. 위험 회피 성공 분석",
        "",
        _risk_avoidance_analysis(missed_candidates),
        "",
        "## 8. 결론",
        "",
        _conclusion(analysis, missed_candidates),
        "",
    ]
    return "\n".join(lines)


def _trade_records_table(analysis: ReportAnalysis) -> str:
    if not analysis.trade_records:
        return ANALYSIS_UNAVAILABLE
    rows = ["| 시간 | 종목 코드 | 종목명 | 구분 | 가격 | 수량 | 금액 | 수익률 | 손익 | 사유 |", "|---|---|---|---|---:|---:|---:|---:|---:|---|"]
    for record in analysis.trade_records:
        rows.append(
            f"| {record.time} | {record.symbol} | {record.name} | {record.side} | {_format_number(record.price)} | {_format_number(record.quantity)} | {_format_money(record.amount)} | {_format_percent(record.return_rate)} | {_format_money(record.profit_loss)} | {record.reason} |"
        )
    return "\n".join(rows)


def _closed_trades_table(analysis: ReportAnalysis) -> str:
    if not analysis.closed_trades:
        return ANALYSIS_UNAVAILABLE
    rows = ["| 종목 코드 | 종목명 | 매수 시간 | 매수 가격 | 매도 시간 | 매도 가격 | 보유 시간 | 수익률 | 실현 손익 | 매수 사유 | 매도 사유 |", "|---|---|---|---:|---|---:|---:|---:|---:|---|---|"]
    for trade in analysis.closed_trades:
        rows.append(
            f"| {trade.symbol} | {trade.name} | {trade.buy_time} | {_format_number(trade.buy_price)} | {trade.sell_time} | {_format_number(trade.sell_price)} | {_format_minutes(trade.hold_minutes)} | {_format_percent(trade.return_rate)} | {_format_money(trade.profit_loss)} | {trade.buy_reason} | {trade.sell_reason} |"
        )
    return "\n".join(rows)


def _missed_candidates_table(candidates: list[MissedTradeCandidate]) -> str:
    if not candidates:
        return ANALYSIS_UNAVAILABLE
    rows = [
        "| 감지 시간 | 종목 코드 | 종목명 | 당시 가격 | 이후 고가 | 이후 저가 | 매수하지 않은 이유 | 충족 조건 | 미충족 조건 | 조건 충족률 | 가상 수익률 | 가상 손익 | 조건 수정 분석 |",
        "|---|---|---|---:|---:|---:|---|---|---|---:|---|---|---|",
    ]
    for candidate in candidates:
        rows.append(
            f"| {candidate.detected_at} | {candidate.symbol} | {candidate.name} | {_format_number(candidate.price)} | {_format_number(candidate.later_high)} | {_format_number(candidate.later_low)} | {candidate.reason} | {', '.join(candidate.satisfied_conditions) or ANALYSIS_UNAVAILABLE} | {', '.join(candidate.failed_conditions) or ANALYSIS_UNAVAILABLE} | {_format_percent(candidate.condition_match_rate)} | {_format_simulation_rates(candidate)} | {_format_simulation_pnl(candidate)} | {candidate.adjustment} |"
        )
    return "\n".join(rows)


def _strategy_analysis(analysis: ReportAnalysis) -> str:
    if not analysis.condition_counts:
        return ANALYSIS_UNAVAILABLE
    best = _top_count(analysis.condition_counts, reverse=False)
    blocker = _top_count(analysis.reject_counts, reverse=True)
    return "\n".join(
        [
            f"- 오늘 가장 잘 작동한 조건: {best}",
            f"- 오늘 가장 방해가 된 조건: {blocker}",
            f"- 불필요하게 엄격했던 조건: {blocker}",
            "- 너무 느슨했던 조건: 분석 불가",
            "- 손절이 적절했는지: 실제 청산 로그가 충분하지 않으면 분석 불가",
            "- 익절이 적절했는지: 실제 청산 로그가 충분하지 않으면 분석 불가",
            "- 진입 타이밍이 빨랐는지/늦었는지: 후보 이후 가격 흐름 기준으로 별도 검토 필요",
            "- 매도 타이밍이 빨랐는지/늦었는지: 체결가와 이후 가격 로그가 부족하면 분석 불가",
        ]
    )


def _missed_opportunity_analysis(candidates: list[MissedTradeCandidate]) -> str:
    positive = [candidate for candidate in candidates if (candidate.simulation.neutral_profit_loss or 0) > 0]
    total = sum(candidate.simulation.neutral_profit_loss or 0 for candidate in positive)
    best = max(positive, key=lambda candidate: candidate.simulation.neutral_profit_loss or 0, default=None)
    return "\n".join(
        [
            f"- 매수하지 않아 놓친 예상 수익: {_format_money(total) if positive else ANALYSIS_UNAVAILABLE}",
            f"- 가장 아쉬운 미진입 후보: {best.symbol if best is not None else ANALYSIS_UNAVAILABLE}",
            f"- 조건 완화가 필요해 보이는 항목: {best.adjustment if best is not None else ANALYSIS_UNAVAILABLE}",
        ]
    )


def _risk_avoidance_analysis(candidates: list[MissedTradeCandidate]) -> str:
    negative = [candidate for candidate in candidates if (candidate.simulation.neutral_profit_loss or 0) < 0]
    total = sum(candidate.simulation.neutral_profit_loss or 0 for candidate in negative)
    filters = sorted({candidate.reason for candidate in negative})
    return "\n".join(
        [
            f"- 매수하지 않아 피한 예상 손실: {_format_money(abs(total)) if negative else ANALYSIS_UNAVAILABLE}",
            f"- 제외 조건이 유효했던 후보: {', '.join(candidate.symbol for candidate in negative[:5]) if negative else ANALYSIS_UNAVAILABLE}",
            f"- 유지해야 할 필터: {', '.join(filters) if filters else ANALYSIS_UNAVAILABLE}",
        ]
    )


def _conclusion(analysis: ReportAnalysis, candidates: list[MissedTradeCandidate]) -> str:
    if analysis.summary.total_sell_count == 0 and not candidates:
        rating = "분석 불가"
    elif analysis.summary.total_realized_profit_loss is not None and analysis.summary.total_realized_profit_loss > 0:
        rating = "B"
    elif analysis.summary.total_realized_profit_loss is not None and analysis.summary.total_realized_profit_loss < 0:
        rating = "D"
    else:
        rating = "C"
    blocker = _top_count(analysis.reject_counts, reverse=True)
    return "\n".join(
        [
            f"- 오늘의 전략 평점: {rating}",
            f"- 오늘의 핵심 문제: {blocker}",
            "- 내일 우선 확인할 부분: 반복적으로 매수를 막은 조건과 후보 이후 가격 흐름",
        ]
    )


def _top_count(values: dict[str, int], reverse: bool) -> str:
    if not values:
        return ANALYSIS_UNAVAILABLE
    key, count = sorted(values.items(), key=lambda item: item[1], reverse=reverse)[0]
    return f"{key} ({count}회)"


def _format_simulation_rates(candidate: MissedTradeCandidate) -> str:
    return f"보수 {_format_percent(candidate.simulation.conservative_return_rate)} / 중립 {_format_percent(candidate.simulation.neutral_return_rate)} / 공격 {_format_percent(candidate.simulation.aggressive_return_rate)}"


def _format_simulation_pnl(candidate: MissedTradeCandidate) -> str:
    return f"보수 {_format_money(candidate.simulation.conservative_profit_loss)} / 중립 {_format_money(candidate.simulation.neutral_profit_loss)} / 공격 {_format_money(candidate.simulation.aggressive_profit_loss)}"


def _format_percent(value: Any) -> str:
    if value is None:
        return ANALYSIS_UNAVAILABLE
    return f"{float(value):.2f}%"


def _format_money(value: Any) -> str:
    if value is None:
        return ANALYSIS_UNAVAILABLE
    return f"{float(value):,.0f}"


def _format_number(value: Any) -> str:
    if value is None:
        return ANALYSIS_UNAVAILABLE
    return f"{float(value):g}"


def _format_minutes(value: Any) -> str:
    if value is None:
        return ANALYSIS_UNAVAILABLE
    return f"{float(value):.1f}분"
