from src.broker.kis_account import KisAccount
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.broker.kis_overseas_order import KisOverseasOrder
from src.logs.trade_logger import get_trade_logger


def calculate_order_quantity(current_price: int, available_cash: int, max_order_amount: int, force_quantity: int | None) -> int:
    """Calculate order quantity from cash and configured order amount.

    @param current_price: Current stock price.
    @param available_cash: Available order cash.
    @param max_order_amount: Maximum amount per order.
    @param force_quantity: Optional forced quantity.
    @returns: Quantity to order, or 0 when order is not possible.
    """
    if current_price <= 0 or available_cash <= 0:
        return 0
    if force_quantity is not None:
        required_cash = current_price * force_quantity
        return force_quantity if required_cash <= available_cash else 0
    order_amount = min(max_order_amount, available_cash)
    return order_amount // current_price


class DryRunRunner:
    def __init__(self, market: KisMarket, account: KisAccount, order: KisOrder, overseas_order: KisOverseasOrder | None = None):
        self.market = market
        self.account = account
        self.order = order
        self.overseas_order = overseas_order
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

    def test_us_buy(self, symbol: str, quantity: int, price: float, exchange: str = "NASD") -> dict:
        """Run a US limit-buy test through KisOverseasOrder.

        @param symbol: Overseas stock symbol.
        @param quantity: Order quantity.
        @param price: Limit price.
        @param exchange: Overseas trading exchange code.
        @returns: Order response.
        """
        if self.overseas_order is None:
            raise RuntimeError("overseas order dependency is not configured")
        self.logger.info("[TEST US BUY] symbol=%s exchange=%s price=%s quantity=%s", symbol, exchange, price, quantity)
        return self.overseas_order.buy_limit(symbol, quantity, price, exchange)

    def test_us_sell(self, symbol: str, quantity: int, price: float, exchange: str = "NASD") -> dict:
        """Run a US limit-sell test through KisOverseasOrder.

        @param symbol: Overseas stock symbol.
        @param quantity: Order quantity.
        @param price: Limit price.
        @param exchange: Overseas trading exchange code.
        @returns: Order response.
        """
        if self.overseas_order is None:
            raise RuntimeError("overseas order dependency is not configured")
        self.logger.info("[TEST US SELL] symbol=%s exchange=%s price=%s quantity=%s", symbol, exchange, price, quantity)
        return self.overseas_order.sell_limit(symbol, quantity, price, exchange)
