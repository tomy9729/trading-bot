from src.config.bot_config import load_bot_config
from src.report.missed_trade_analyzer import analyze_missed_candidates
from src.report.report_analyzer import analyze_trades
from src.report.report_parser import parse_log_file, parse_log_line
from src.report.report_writer import create_report_markdown


def test_parse_text_log_preserves_symbol_leading_zero():
    event = parse_log_line("2026-06-16 09:14:52,974 INFO [BUY DONE] market=KR symbol=005930 name='삼성전자' entry_price=1010 quantity=1 response={'dry_run': True}")

    assert event is not None
    assert event.event_type == "BUY_ORDER_FILLED"
    assert event.data["symbol"] == "005930"
    assert event.data["name"] == "삼성전자"
    assert event.data["entry_price"] == 1010


def test_report_analyzes_closed_trade_profit_loss(tmp_path):
    log_path = tmp_path / "trade_20260616.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-06-16 09:00:00,000 INFO [BUY CHECK] market=domestic symbol=005930 name='삼성전자' signal=Signal(signal='BUY', allowed=True, reason='VWAP_HOLD_VOLUME_BREAKOUT_MARKET_CONFIRMED', details={'symbol': '005930', 'current_price': 1000, 'vwap': 990, 'recent_high': 995, 'spread_rate': 0.1, 'execution_strength': 100.0, 'vwap_hold_candle_count': 3, 'upper_wick_rate': 0.0, 'market_direction_rate': 0.2, 'volume_declining': False, 'market': 'KR', 'volume_multiplier': 3.0})",
                "2026-06-16 09:00:01,000 INFO [BUY DONE] market=KR symbol=005930 name='삼성전자' entry_price=1000 quantity=2 response={'dry_run': True}",
                "2026-06-16 09:05:00,000 INFO [SELL CHECK] market=domestic symbol=005930 name='삼성전자' signal=Signal(signal='SELL', allowed=True, reason='FIRST_TAKE_PROFIT', details={'symbol': '005930', 'current_price': 1010, 'vwap': 1005, 'recent_high': 1010, 'spread_rate': 0.1, 'execution_strength': 100.0, 'vwap_hold_candle_count': 4, 'upper_wick_rate': 0.0, 'market_direction_rate': 0.2, 'volume_declining': False, 'profit_rate': 1.0, 'hold_minutes': 5.0})",
                "2026-06-16 09:05:01,000 INFO [SELL DONE] market=KR symbol=005930 name='삼성전자' quantity=2 reason=FIRST_TAKE_PROFIT response={'dry_run': True}",
            ]
        ),
        encoding="utf-8",
    )

    analysis = analyze_trades(parse_log_file(log_path))

    assert analysis.summary.total_buy_count == 1
    assert analysis.summary.total_sell_count == 1
    assert analysis.summary.total_realized_profit_loss == 20
    assert analysis.trade_records[0].name == "삼성전자"
    assert analysis.closed_trades[0].return_rate == 1.0
    assert analysis.closed_trades[0].hold_minutes == 5.0


def test_missed_candidate_and_markdown_include_adjustment(tmp_path):
    log_path = tmp_path / "trade_20260616.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-06-16 09:00:00,000 INFO [BUY CHECK] market=domestic symbol=005930 name='삼성전자' signal=Signal(signal='HOLD', allowed=False, reason='VOLUME_SPIKE_NOT_ENOUGH', details={'symbol': '005930', 'current_price': 1000, 'vwap': 990, 'recent_high': 995, 'spread_rate': 0.1, 'execution_strength': 100.0, 'vwap_hold_candle_count': 3, 'upper_wick_rate': 0.0, 'market_direction_rate': 0.2, 'volume_declining': False, 'market': 'KR', 'volume_multiplier': 1.8})",
                "2026-06-16 09:01:00,000 INFO [BUY CHECK] market=domestic symbol=005930 name='삼성전자' signal=Signal(signal='HOLD', allowed=False, reason='BREAKOUT_FAILED', details={'symbol': '005930', 'current_price': 1020, 'vwap': 990, 'recent_high': 1020, 'spread_rate': 0.1, 'execution_strength': 100.0, 'vwap_hold_candle_count': 3, 'upper_wick_rate': 0.0, 'market_direction_rate': 0.2, 'volume_declining': False, 'market': 'KR', 'volume_multiplier': 3.0})",
            ]
        ),
        encoding="utf-8",
    )
    events = parse_log_file(log_path)
    analysis = analyze_trades(events)
    candidates = analyze_missed_candidates(events, load_bot_config())

    markdown = create_report_markdown("2026-06-16", analysis, candidates)

    assert candidates
    assert candidates[0].symbol == "005930"
    assert candidates[0].name == "삼성전자"
    assert "거래량 기준" in markdown
    assert "매수될 뻔한 후보 분석" in markdown


def test_report_includes_strategy_and_pnl_reconciliation():
    analysis = analyze_trades([])

    markdown = create_report_markdown(
        "2026-06-23",
        analysis,
        [],
        account_snapshot={
            "daily_realized_pnl": 750,
            "broker_daily_realized_pnl": 800,
            "realized_pnl_difference": -50,
            "cumulative_cost": 150,
        },
        strategy_metadata={
            "strategy_name": "vwap-volume-breakout",
            "strategy_version": "abc123def456",
        },
    )

    assert "## 2. 운영 정합성" in markdown
    assert "전략 버전: abc123def456" in markdown
    assert "실현손익 차이: -50" in markdown
    assert "손익 정합성: 확인 필요" in markdown
