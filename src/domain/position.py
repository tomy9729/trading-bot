from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Position:
    """Current holding information for one symbol."""

    symbol: str
    quantity: int | float
    average_price: int | float
    entry_time: datetime
    entry_reason: str | None = None
    stop_reference_price: int | float | None = None
    peak_price: int | float | None = None


@dataclass(frozen=True)
class PositionState:
    """Read-only position collection used by strategy checks."""

    positions: tuple[Position, ...] = ()

    def has_symbol(self, symbol: str) -> bool:
        """Return whether a position exists for the symbol.

        @param symbol: Stock symbol to check.
        @returns: True when the symbol is currently held.
        """
        return self.get_position(symbol) is not None

    def get_position(self, symbol: str) -> Position | None:
        """Return the position for the symbol, if any.

        @param symbol: Stock symbol to find.
        @returns: Matching position or None.
        """
        return next((position for position in self.positions if position.symbol == symbol), None)
