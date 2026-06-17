import json

from src.logs.trade_logger import write_trade_event


class _CustomValue:
    def __str__(self) -> str:
        return "custom-value"


def test_write_trade_event_writes_jsonl_with_safe_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    write_trade_event(
        "strategy_decision",
        {
            "market": "KR",
            "symbol": "005930",
            "symbol_name": _CustomValue(),
            "decision": {"matched_conditions": ("PRICE_BREAKOUT",)},
        },
    )

    log_files = list((tmp_path / "logs").glob("trade_events_*.jsonl"))
    assert len(log_files) == 1

    event = json.loads(log_files[0].read_text(encoding="utf-8"))
    assert event["schema_version"] == 1
    assert event["event_type"] == "strategy_decision"
    assert event["symbol"] == "005930"
    assert event["symbol_name"] == "custom-value"
    assert event["decision"]["matched_conditions"] == ["PRICE_BREAKOUT"]
