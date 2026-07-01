from pathlib import Path
from typing import Any

from src.config.runtime_paths import get_report_dir
from src.report.missed_trade_analyzer import MissedTradeCandidate
from src.report.report_analyzer import ReportAnalysis


ANALYSIS_UNAVAILABLE = "분석 불가"


def get_default_report_path(report_date: str) -> Path:
    """Create the default daily report path.

    @param report_date: Normalized YYYY-MM-DD date.
    @returns: reports/YYYY-MM-DD-daily-trading-report.md path.
    """
    return get_report_dir() / f"{report_date}-daily-trading-report.md"


def write_report(
    report_date: str,
    analysis: ReportAnalysis,
    missed_candidates: list[MissedTradeCandidate],
    save: bool,
    account_snapshot: dict[str, Any] | None = None,
    strategy_metadata: dict[str, Any] | None = None,
) -> Path | None:
    """Create a daily trading report and optionally save it.

    @param report_date: Normalized YYYY-MM-DD date.
    @param analysis: Actual trade analysis.
    @param missed_candidates: Missed candidate analysis.
    @param save: Whether to save the report file.
    @param account_snapshot: Optional latest account snapshot for the date.
    @param strategy_metadata: Optional active strategy metadata.
    @returns: Saved report path, or None when save is false.
    """
    content = create_report_markdown(
        report_date,
        analysis,
        missed_candidates,
        account_snapshot,
        strategy_metadata,
    )
    if not save:
        print(content)
        return None
    report_path = get_default_report_path(report_date)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
    return report_path


def create_report_markdown(
    report_date: str,
    analysis: ReportAnalysis,
    missed_candidates: list[MissedTradeCandidate],
    account_snapshot: dict[str, Any] | None = None,
    strategy_metadata: dict[str, Any] | None = None,
) -> str:
    """Create Markdown content for a daily trading report.

    @param report_date: Normalized YYYY-MM-DD date.
    @param analysis: Actual trade analysis.
    @param missed_candidates: Missed candidate analysis.
    @param account_snapshot: Optional latest account snapshot for the date.
    @param strategy_metadata: Optional active strategy metadata.
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
        "## Expected Profit Simulation",
        "",
        _expected_profit_summary(missed_candidates),
        "",
        "## 2. 운영 정합성",
        "",
        _operation_reconciliation(account_snapshot, strategy_metadata),
        "",
        "## 3. 실제 매수/매도 기록",
        "",
        _trade_records_table(analysis),
        "",
        "## 4. 종목별 상세 결과",
        "",
        _closed_trades_table(analysis),
        "",
        "## 5. 매수될 뻔한 후보 분석",
        "",
        _missed_candidates_table(missed_candidates),
        "",
        "## 6. 전략 개선 분석",
        "",
        _strategy_analysis(analysis),
        "",
        "## 7. 놓친 기회 분석",
        "",
        _missed_opportunity_analysis(missed_candidates),
        "",
        "## 8. 위험 회피 성공 분석",
        "",
        _risk_avoidance_analysis(missed_candidates),
        "",
        "## 9. 결론",
        "",
        _conclusion(analysis, missed_candidates),
        "",
    ]
    return "\n".join(lines)


def _trade_records_table(analysis: ReportAnalysis) -> str:
    if not analysis.trade_records:
        return ANALYSIS_UNAVAILABLE
    rows = ["| 시간 | 종목 코드 | 종목명 | 구분 | 가격 | 수량 | 금액 | 거래비용 | 수익률 | 손익 | 사유 |", "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for record in analysis.trade_records:
        rows.append(
            f"| {record.time} | {record.symbol} | {record.name} | {record.side} | {_format_number(record.price)} | {_format_number(record.quantity)} | {_format_money(record.amount)} | {_format_money(record.total_cost)} | {_format_percent(record.return_rate)} | {_format_money(record.profit_loss)} | {record.reason} |"
        )
    return "\n".join(rows)


def _closed_trades_table(analysis: ReportAnalysis) -> str:
    if not analysis.closed_trades:
        return ANALYSIS_UNAVAILABLE
    rows = ["| 종목 코드 | 종목명 | 매수 시간 | 매수 가격 | 매도 시간 | 매도 가격 | 보유 시간 | 총손익 | 거래비용 | 순수익률 | 순손익 | 매수 사유 | 매도 사유 |", "|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for trade in analysis.closed_trades:
        rows.append(
            f"| {trade.symbol} | {trade.name} | {trade.buy_time} | {_format_number(trade.buy_price)} | {trade.sell_time} | {_format_number(trade.sell_price)} | {_format_minutes(trade.hold_minutes)} | {_format_money(trade.gross_profit_loss)} | {_format_money(trade.total_cost)} | {_format_percent(trade.return_rate)} | {_format_money(trade.profit_loss)} | {trade.buy_reason} | {trade.sell_reason} |"
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


def _operation_reconciliation(
    account_snapshot: dict[str, Any] | None,
    strategy_metadata: dict[str, Any] | None,
) -> str:
    lines = []
    tolerance = _to_float(strategy_metadata.get("realized_pnl_difference_tolerance")) if strategy_metadata else None
    if strategy_metadata:
        lines.extend(
            [
                f"- 전략명: {strategy_metadata.get('strategy_name') or ANALYSIS_UNAVAILABLE}",
                f"- 전략 버전: {strategy_metadata.get('strategy_version') or ANALYSIS_UNAVAILABLE}",
            ]
        )
    if account_snapshot:
        difference = account_snapshot.get("realized_pnl_difference")
        reconciliation_status = _pnl_reconciliation_status(difference, tolerance)
        lines.extend(
            [
                f"- 내부 계산 실현손익: {_format_money(account_snapshot.get('daily_realized_pnl'))}",
                f"- 증권사 실현손익: {_format_money(account_snapshot.get('broker_daily_realized_pnl'))}",
                f"- 실현손익 차이: {_format_money(difference)}",
                f"- 실현손익 허용오차: {_format_money(tolerance)}",
                f"- 누적 거래비용: {_format_money(account_snapshot.get('cumulative_cost'))}",
                f"- 손익 정합성: {reconciliation_status}",
            ]
        )
    return "\n".join(lines) if lines else ANALYSIS_UNAVAILABLE


def _expected_profit_summary(candidates: list[MissedTradeCandidate]) -> str:
    if not candidates:
        return ANALYSIS_UNAVAILABLE
    neutral_values = [
        candidate.simulation.neutral_profit_loss
        for candidate in candidates
        if candidate.simulation.neutral_profit_loss is not None
    ]
    neutral_rates = [
        candidate.simulation.neutral_return_rate
        for candidate in candidates
        if candidate.simulation.neutral_return_rate is not None
    ]
    if not neutral_values:
        return ANALYSIS_UNAVAILABLE
    wins = [value for value in neutral_values if value > 0]
    best = max(
        candidates,
        key=lambda candidate: candidate.simulation.neutral_profit_loss
        if candidate.simulation.neutral_profit_loss is not None
        else float("-inf"),
    )
    return "\n".join(
        [
            f"- Expected candidate count: {len(neutral_values)}",
            f"- Expected net profit per 1 share: {_format_money(sum(neutral_values))}",
            f"- Expected average return: {_format_percent(sum(neutral_rates) / len(neutral_rates)) if neutral_rates else ANALYSIS_UNAVAILABLE}",
            f"- Expected win rate: {_format_percent((len(wins) / len(neutral_values)) * 100)}",
            f"- Best expected candidate: {best.symbol} {_format_money(best.simulation.neutral_profit_loss)} / {_format_percent(best.simulation.neutral_return_rate)}",
        ]
    )


def _pnl_reconciliation_status(difference: Any, tolerance: float | None) -> str:
    """Create a PnL reconciliation status.

    @param difference: Internal minus broker realized PnL.
    @param tolerance: Allowed absolute difference.
    @returns: Reconciliation status text.
    """
    value = _to_float(difference)
    if value is None:
        return "확인 필요"
    if value == 0:
        return "일치"
    if tolerance is not None and abs(value) <= tolerance:
        return "허용 범위"
    return "확인 필요"


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


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: Any) -> str:
    if value is None:
        return ANALYSIS_UNAVAILABLE
    return f"{float(value):g}"


def _format_minutes(value: Any) -> str:
    if value is None:
        return ANALYSIS_UNAVAILABLE
    return f"{float(value):.1f}분"
