from dataclasses import dataclass, field
from typing import Any, Protocol


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
    response: dict[str, Any] = field(default_factory=dict)


class MarketOrderGateway(Protocol):
    def buy_market(self, symbol: str, quantity: int) -> dict[str, Any]:
        """Place a domestic market buy order."""
        ...

    def sell_market(self, symbol: str, quantity: int) -> dict[str, Any]:
        """Place a domestic market sell order."""
        ...
