from src.broker.kis_account import KisAccount
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.logs.trade_logger import get_trade_logger


class LiveRunner:
    def __init__(
        self,
        market: KisMarket,
        account: KisAccount,
        order: KisOrder,
    ):
        self.market = market
        self.account = account
        self.order = order
        self.logger = get_trade_logger()

    def health_check(self, symbol: str) -> dict:
        """Check live KIS API connectivity without placing an order.

        @param symbol: Six-digit domestic stock code.
        @returns: Current price, orderbook, available cash, and balance count.
        """
        price = self.market.get_current_price(symbol)
        orderbook = self.market.get_orderbook(symbol)
        available_cash = self.account.get_available_cash(symbol)
        balance = self.account.get_balance()
        result = {
            "symbol": symbol,
            "current_price": price,
            "orderbook": orderbook,
            "available_cash": available_cash,
            "balance_count": len(balance),
        }
        self.logger.info("[LIVE HEALTH CHECK] %s", result)
        return result
