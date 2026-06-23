from dataclasses import dataclass


@dataclass(frozen=True)
class TradeCostResult:
    gross_profit_loss: float
    gross_return_rate: float
    buy_fee: float
    sell_fee: float
    sell_tax: float
    slippage_cost: float
    total_cost: float
    net_profit_loss: float
    net_return_rate: float


def calculate_trade_cost_result(
    entry_price: float,
    exit_price: float,
    quantity: int | float,
    *,
    buy_fee_percent: float,
    sell_fee_percent: float,
    sell_tax_percent: float,
    sell_slippage_percent: float = 0.0,
) -> TradeCostResult:
    """Calculate gross and net trade results including transaction costs.

    @param entry_price: Actual or estimated average buy price.
    @param exit_price: Actual or estimated sell price.
    @param quantity: Trade quantity.
    @param buy_fee_percent: Buy commission rate in percent.
    @param sell_fee_percent: Sell commission rate in percent.
    @param sell_tax_percent: Sell transaction tax rate in percent.
    @param sell_slippage_percent: Estimated sell slippage rate in percent.
    @returns: Gross and net profit/loss calculation.
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be greater than 0")
    if exit_price < 0:
        raise ValueError("exit_price must be greater than or equal to 0")
    if quantity <= 0:
        raise ValueError("quantity must be greater than 0")

    buy_amount = float(entry_price) * float(quantity)
    sell_amount = float(exit_price) * float(quantity)
    gross_profit_loss = sell_amount - buy_amount
    buy_fee = buy_amount * (buy_fee_percent / 100)
    sell_fee = sell_amount * (sell_fee_percent / 100)
    sell_tax = sell_amount * (sell_tax_percent / 100)
    slippage_cost = sell_amount * (sell_slippage_percent / 100)
    total_cost = buy_fee + sell_fee + sell_tax + slippage_cost
    net_profit_loss = gross_profit_loss - total_cost
    cost_basis = buy_amount + buy_fee

    return TradeCostResult(
        gross_profit_loss=gross_profit_loss,
        gross_return_rate=(gross_profit_loss / buy_amount) * 100,
        buy_fee=buy_fee,
        sell_fee=sell_fee,
        sell_tax=sell_tax,
        slippage_cost=slippage_cost,
        total_cost=total_cost,
        net_profit_loss=net_profit_loss,
        net_return_rate=(net_profit_loss / cost_basis) * 100,
    )
