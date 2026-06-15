from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: str = "MARKET"


@dataclass(frozen=True)
class OrderResult:
    requested: OrderRequest
    dry_run: bool
    response: Dict[str, Any] = field(default_factory=dict)
