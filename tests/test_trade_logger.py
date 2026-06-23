import json

from src.logs.trade_logger import set_trade_event_sink, write_trade_event


class _CustomValue:
    def __str__(self) -> str:
        return "custom-value"


def test_write_trade_event_writes_jsonl_with_safe_values(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("TRADING_LOG_DIR", str(log_dir))

    write_trade_event(
        "strategy_decision",
        {
            "market": "KR",
            "symbol": "005930",
            "symbol_name": _CustomValue(),
            "decision": {"matched_conditions": ("PRICE_BREAKOUT",)},
        },
    )

    log_files = list(log_dir.glob("trade_events_*.jsonl"))
    assert len(log_files) == 1

    event = json.loads(log_files[0].read_text(encoding="utf-8"))
    assert event["schema_version"] == 1
    assert event["event_type"] == "strategy_decision"
    assert event["symbol"] == "005930"
    assert event["symbol_name"] == "custom-value"
    assert event["decision"]["matched_conditions"] == ["PRICE_BREAKOUT"]


def test_write_trade_event_sends_same_event_to_sink(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("TRADING_LOG_DIR", str(log_dir))
    saved_events = []
    set_trade_event_sink(saved_events.append)
    try:
        write_trade_event("order_skipped", {"market": "KR", "symbol": "005930", "reason": "TEST"})
    finally:
        set_trade_event_sink(None)

    file_event = json.loads(next(log_dir.glob("trade_events_*.jsonl")).read_text(encoding="utf-8"))

    assert saved_events == [file_event]
