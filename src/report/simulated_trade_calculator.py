from dataclasses import dataclass

from src.risk.trading_cost import calculate_trade_cost_result


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
    *,
    buy_fee_percent: float = 0.0,
    sell_fee_percent: float = 0.0,
    sell_tax_percent: float = 0.0,
    sell_slippage_percent: float = 0.0,
) -> SimulatedTradeResult:
    """Calculate conservative, neutral, and aggressive virtual trade results.

    @param entry_price: Candidate detection price.
    @param later_low: Lowest later observed price.
    @param later_last: Last later observed price.
    @param later_high: Highest later observed price.
    @param quantity: Assumed quantity.
    @param buy_fee_percent: Estimated buy commission rate in percent.
    @param sell_fee_percent: Estimated sell commission rate in percent.
    @param sell_tax_percent: Estimated sell transaction tax rate in percent.
    @param sell_slippage_percent: Estimated sell slippage rate in percent.
    @returns: Simulated virtual trade result.
    """
    if entry_price is None or entry_price <= 0 or quantity <= 0:
        return SimulatedTradeResult(None, None, None, None, None, None)
    conservative_rate = _return_rate(
        entry_price,
        later_low,
        quantity,
        buy_fee_percent,
        sell_fee_percent,
        sell_tax_percent,
        sell_slippage_percent,
    )
    neutral_rate = _return_rate(
        entry_price,
        later_last,
        quantity,
        buy_fee_percent,
        sell_fee_percent,
        sell_tax_percent,
        sell_slippage_percent,
    )
    aggressive_rate = _return_rate(
        entry_price,
        later_high,
        quantity,
        buy_fee_percent,
        sell_fee_percent,
        sell_tax_percent,
        sell_slippage_percent,
    )
    return SimulatedTradeResult(
        conservative_rate,
        neutral_rate,
        aggressive_rate,
        _profit_loss(
            entry_price,
            later_low,
            quantity,
            buy_fee_percent,
            sell_fee_percent,
            sell_tax_percent,
            sell_slippage_percent,
        ),
        _profit_loss(
            entry_price,
            later_last,
            quantity,
            buy_fee_percent,
            sell_fee_percent,
            sell_tax_percent,
            sell_slippage_percent,
        ),
        _profit_loss(
            entry_price,
            later_high,
            quantity,
            buy_fee_percent,
            sell_fee_percent,
            sell_tax_percent,
            sell_slippage_percent,
        ),
    )


def _return_rate(
    entry_price: float | int,
    exit_price: float | int | None,
    quantity: float | int,
    buy_fee_percent: float,
    sell_fee_percent: float,
    sell_tax_percent: float,
    sell_slippage_percent: float,
) -> float | None:
    if exit_price is None:
        return None
    return calculate_trade_cost_result(
        float(entry_price),
        float(exit_price),
        quantity,
        buy_fee_percent=buy_fee_percent,
        sell_fee_percent=sell_fee_percent,
        sell_tax_percent=sell_tax_percent,
        sell_slippage_percent=sell_slippage_percent,
    ).net_return_rate


def _profit_loss(
    entry_price: float | int,
    exit_price: float | int | None,
    quantity: float | int,
    buy_fee_percent: float,
    sell_fee_percent: float,
    sell_tax_percent: float,
    sell_slippage_percent: float,
) -> float | None:
    if exit_price is None:
        return None
    return calculate_trade_cost_result(
        float(entry_price),
        float(exit_price),
        quantity,
        buy_fee_percent=buy_fee_percent,
        sell_fee_percent=sell_fee_percent,
        sell_tax_percent=sell_tax_percent,
        sell_slippage_percent=sell_slippage_percent,
    ).net_profit_loss
