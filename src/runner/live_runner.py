from src.broker.kis_account import KisAccount
from src.broker.kis_market import KisMarket
from src.broker.kis_order import KisOrder
from src.broker.kis_overseas_account import KisOverseasAccount
from src.broker.kis_overseas_market import KisOverseasMarket
from src.broker.kis_overseas_order import KisOverseasOrder
from src.logs.trade_logger import get_trade_logger


class LiveRunner:
    def __init__(
        self,
        market: KisMarket,
        account: KisAccount,
        order: KisOrder,
        overseas_market: KisOverseasMarket | None = None,
        overseas_account: KisOverseasAccount | None = None,
        overseas_order: KisOverseasOrder | None = None,
    ):
        self.market = market
        self.account = account
        self.order = order
        self.overseas_market = overseas_market
        self.overseas_account = overseas_account
        self.overseas_order = overseas_order
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

    def overseas_health_check(self, symbol: str, quote_exchange: str = "NAS", order_exchange: str = "NASD") -> dict:
        """Check overseas KIS API connectivity without placing an order.

        @param symbol: Overseas stock symbol.
        @param quote_exchange: Quote exchange code, for example NAS.
        @param order_exchange: Trading exchange code, for example NASD.
        @returns: Current price, orderbook, available cash, and balance count.
        """
        if self.overseas_market is None or self.overseas_account is None:
            raise RuntimeError("overseas runner dependencies are not configured")
        price = self.overseas_market.get_current_price(symbol, quote_exchange)
        orderbook = self.overseas_market.get_orderbook(symbol, quote_exchange)
        available_cash = self.overseas_account.get_available_cash(symbol, price, order_exchange)
        balance = self.overseas_account.get_balance(order_exchange, "USD")
        result = {
            "symbol": symbol,
            "current_price": price,
            "orderbook": orderbook,
            "available_cash": available_cash,
            "balance_count": len(balance),
        }
        self.logger.info("[US LIVE HEALTH CHECK] %s", result)
        return result
