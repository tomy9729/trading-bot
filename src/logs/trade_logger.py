import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Callable

from src.config.runtime_paths import get_log_dir


_trade_event_sink: Callable[[dict[str, Any]], Any] | None = None


def get_trade_logger(name: str = "trade") -> logging.Logger:
    """Create or return the daily trade logger.

    @param name: Logger name.
    @returns: Configured logger writing to logs/trade_YYYYMMDD.log and stdout.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    log_dir = get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"trade_{datetime.now().strftime('%Y%m%d')}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def write_trade_event(event_type: str, payload: dict[str, Any]) -> None:
    """Write one structured trading event as JSON Lines.

    @param event_type: Stable event type name.
    @param payload: Event payload.
    """
    log_dir = get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"trade_events_{datetime.now().strftime('%Y%m%d')}.jsonl"
    event = {
        **payload,
        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "schema_version": 1,
        "event_type": event_type,
    }
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(_to_jsonable(event), ensure_ascii=False, sort_keys=True))
        file.write("\n")
    if _trade_event_sink is not None:
        try:
            _trade_event_sink(_to_jsonable(event))
        except Exception:
            get_trade_logger().exception("[EVENT DB SAVE FAILED] event_type=%s", event_type)


def set_trade_event_sink(sink: Callable[[dict[str, Any]], Any] | None) -> None:
    """Set the optional structured event persistence callback.

    @param sink: Callback receiving one JSON-safe event, or None to disable.
    @mutate: Replaces the process-wide event persistence callback.
    """
    global _trade_event_sink
    _trade_event_sink = sink


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, datetime):
        return value.astimezone().isoformat(timespec="milliseconds")
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
