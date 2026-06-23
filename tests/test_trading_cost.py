from src.risk.trading_cost import calculate_trade_cost_result


def test_calculate_trade_cost_result_includes_fees_tax_and_slippage():
    result = calculate_trade_cost_result(
        100000,
        101000,
        1,
        buy_fee_percent=0.015,
        sell_fee_percent=0.015,
        sell_tax_percent=0.2,
        sell_slippage_percent=0.05,
    )

    assert result.gross_profit_loss == 1000
    assert round(result.total_cost, 2) == 282.65
    assert round(result.net_profit_loss, 2) == 717.35

