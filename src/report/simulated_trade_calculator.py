from dataclasses import dataclass


@dataclass(frozen=True)
class SimulatedTradeResult:
    conservative_return_rate: float | None
    neutral_return_rate: float | None
    aggressive_return_rate: float | None
    conservative_profit_loss: float | None
    neutral_profit_loss: float | None
    aggressive_profit_loss: float | None


def calculate_simulated_trade(
    entry_price: float | int | None,
    later_low: float | int | None,
    later_last: float | int | None,
    later_high: float | int | None,
    quantity: float | int,
) -> SimulatedTradeResult:
    """Calculate conservative, neutral, and aggressive virtual trade results.

    @param entry_price: Candidate detection price.
    @param later_low: Lowest later observed price.
    @param later_last: Last later observed price.
    @param later_high: Highest later observed price.
    @param quantity: Assumed quantity.
    @returns: Simulated virtual trade result.
    """
    if entry_price is None or entry_price <= 0 or quantity <= 0:
        return SimulatedTradeResult(None, None, None, None, None, None)
    conservative_rate = _return_rate(entry_price, later_low)
    neutral_rate = _return_rate(entry_price, later_last)
    aggressive_rate = _return_rate(entry_price, later_high)
    return SimulatedTradeResult(
        conservative_rate,
        neutral_rate,
        aggressive_rate,
        _profit_loss(entry_price, later_low, quantity),
        _profit_loss(entry_price, later_last, quantity),
        _profit_loss(entry_price, later_high, quantity),
    )


def _return_rate(entry_price: float | int, exit_price: float | int | None) -> float | None:
    if exit_price is None:
        return None
    return ((float(exit_price) - float(entry_price)) / float(entry_price)) * 100


def _profit_loss(entry_price: float | int, exit_price: float | int | None, quantity: float | int) -> float | None:
    if exit_price is None:
        return None
    return (float(exit_price) - float(entry_price)) * float(quantity)
