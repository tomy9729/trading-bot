from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int | float
    average_price: int | float
    entry_time: datetime
    entry_reason: str | None = None
    stop_reference_price: int | float | None = None
    peak_price: int | float | None = None


@dataclass(frozen=True)
class PositionState:
    positions: tuple[Position, ...] = ()

    def has_symbol(self, symbol: str) -> bool:
        return any(position.symbol == symbol for position in self.positions)

    def get_position(self, symbol: str) -> Optional[Position]:
        for position in self.positions:
            if position.symbol == symbol:
                return position
        return None
