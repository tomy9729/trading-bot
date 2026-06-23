import ast
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.runtime_paths import get_log_dir


ANALYSIS_UNAVAILABLE = "분석 불가"
LOG_LINE_PATTERN = re.compile(r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (?P<level>\w+) (?P<message>.*)$")
SIGNAL_PATTERN = re.compile(
    r"Signal\(signal='(?P<signal>[^']+)', allowed=(?P<allowed>True|False), reason='(?P<reason>[^']+)', details=(?P<details>\{.*\})\)"
)
KEY_VALUE_PATTERN = re.compile(r"(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)=(?P<value>('[^']*'|\"[^\"]*\"|\S+))")


@dataclass(frozen=True)
class ReportEvent:
    timestamp: datetime
    event_type: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def parse_report_date(value: str) -> str:
    """Parse a report date argument.

    @param value: Date value in YYYY-MM-DD format or today.
    @returns: Normalized YYYY-MM-DD date.
    """
    if value == "today":
        return datetime.now().strftime("%Y-%m-%d")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def get_default_log_path(report_date: str) -> Path:
    """Create the default trade log path for a report date.

    @param report_date: Normalized YYYY-MM-DD date.
    @returns: logs/trade_YYYYMMDD.log path.
    """
    return get_log_dir() / f"trade_{report_date.replace('-', '')}.log"


def parse_log_file(log_path: Path) -> list[ReportEvent]:
    """Parse text or JSON Lines trading logs.

    @param log_path: Log file path.
    @returns: Parsed report events.
    """
    if not log_path.exists():
        return []
    events = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        event = parse_log_line(line)
        if event is not None:
            events.append(event)
    return events


def parse_log_line(line: str) -> ReportEvent | None:
    """Parse one log line.

    @param line: Raw log line.
    @returns: Parsed event, or None when the line is not supported.
    """
    text = line.strip()
    if not text:
        return None
    json_event = _parse_json_event(text)
    if json_event is not None:
        return json_event

    match = LOG_LINE_PATTERN.match(text)
    if match is None:
        return None
    timestamp = datetime.strptime(match.group("time"), "%Y-%m-%d %H:%M:%S,%f")
    message = match.group("message")
    event_type = _get_text_event_type(message)
    data = _parse_text_event_data(message)
    return ReportEvent(timestamp=timestamp, event_type=event_type, message=message, data=data)


def _parse_json_event(text: str) -> ReportEvent | None:
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    timestamp_value = payload.get("timestamp") or payload.get("time")
    event_type = str(payload.get("event") or payload.get("event_type") or ANALYSIS_UNAVAILABLE)
    if timestamp_value is None:
        return None
    timestamp = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
    data = dict(payload)
    return ReportEvent(timestamp=timestamp.replace(tzinfo=None), event_type=event_type, message=text, data=data)


def _get_text_event_type(message: str) -> str:
    if message.startswith("[BUY CHECK]"):
        return "BUY_CONDITION_CHECKED"
    if message.startswith("[SELL CHECK]"):
        return "SELL_CONDITION_CHECKED"
    if message.startswith("[BUY DONE]"):
        return "BUY_ORDER_FILLED"
    if message.startswith("[SELL DONE]"):
        return "SELL_ORDER_FILLED"
    if message.startswith("[BUY SKIP]"):
        return "MISSED_BUY_CANDIDATE"
    if message.startswith("[WATCHLIST EXCLUDE]"):
        return "RISK_FILTER_REJECTED"
    if message.startswith("[ORDER REQUEST]"):
        return "BUY_ORDER_SUBMITTED" if "side=BUY" in message else "SELL_ORDER_SUBMITTED"
    if message.startswith("[ORDER FAILED]"):
        return "BUY_ORDER_REJECTED" if "side=BUY" in message else "SELL_ORDER_REJECTED"
    return "LOG"


def _parse_text_event_data(message: str) -> dict[str, Any]:
    data = _parse_key_values(message)
    signal_match = SIGNAL_PATTERN.search(message)
    if signal_match is not None:
        data["signal"] = signal_match.group("signal")
        data["allowed"] = signal_match.group("allowed") == "True"
        data["reason"] = signal_match.group("reason")
        try:
            details = ast.literal_eval(signal_match.group("details"))
            if isinstance(details, dict):
                data["details"] = details
                data.update({f"detail_{key}": value for key, value in details.items()})
        except (SyntaxError, ValueError):
            data["details"] = {}
    return data


def _parse_key_values(message: str) -> dict[str, Any]:
    result = {}
    for match in KEY_VALUE_PATTERN.finditer(message):
        key = match.group("key")
        value = match.group("value").strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')):
            value = value[1:-1]
        result[key] = value if key in {"symbol", "pdno", "prdt_code"} else _coerce_value(value)
    return result


def _coerce_value(value: str) -> Any:
    if value in {"True", "False"}:
        return value == "True"
    if value in {"None", "null"}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.rstrip(",")
