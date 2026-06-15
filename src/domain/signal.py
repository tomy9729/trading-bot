from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class Signal:
    signal: str
    allowed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


NO_SIGNAL = Signal(signal="HOLD", allowed=False, reason="NO_SIGNAL")
