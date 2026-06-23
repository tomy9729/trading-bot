from src.broker.kis_account import KisAccount
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.logs.trade_logger import get_trade_logger


def calculate_order_quantity(available_buy_quantity: int, force_quantity: int | None) -> int:
    """Calculate order quantity from the quantity allowed by the broker.

    @param available_buy_quantity: Maximum market-buy quantity returned by KIS.
    @param force_quantity: Optional forced quantity.
    @returns: Quantity to order, or 0 when order is not possible.
    """
    if available_buy_quantity <= 0:
        return 0
    if force_quantity is not None:
        return force_quantity if force_quantity <= available_buy_quantity else 0
    return available_buy_quantity


class DryRunRunner:
    def __init__(self, market: KisMarket, account: KisAccount, order: KisOrder):
        self.market = market
        self.account = account
        self.order = order
        self.logger = get_trade_logger()

    def test_buy(self, symbol: str, quantity: int = 1) -> dict:
        """Run a dry-run or live-routed test buy through KisOrder.

        @param symbol: Six-digit domestic stock code.
        @param quantity: Order quantity.
        @returns: Order response.
        """
        self.logger.info("[TEST BUY] symbol=%s quantity=%s", symbol, quantity)
        return self.order.buy_market(symbol, quantity)

    def test_sell(self, symbol: str, quantity: int = 1) -> dict:
        """Run a dry-run or live-routed test sell through KisOrder.

        @param symbol: Six-digit domestic stock code.
        @param quantity: Order quantity.
        @returns: Order response.
        """
        self.logger.info("[TEST SELL] symbol=%s quantity=%s", symbol, quantity)
        return self.order.sell_market(symbol, quantity)
