from datetime import datetime
from decimal import Decimal
from typing import Any, Dict

from src.broker.kis_client import KisClient
from src.domain.order import OrderRequest, OrderResult
from src.logs.trade_logger import get_trade_logger
from src.runner.market_hours import MarketHours


class KisOverseasOrder:
    US_ORDER_EXCHANGES = {"NASD", "NYSE", "AMEX"}

    def __init__(self, client: KisClient, market_hours: MarketHours | None = None):
        self.client = client
        self.market_hours = market_hours or MarketHours()
        self.logger = get_trade_logger()

    def buy_limit(self, symbol: str, quantity: int | float | Decimal, price: float, exchange: str = "NASD") -> Dict[str, Any]:
        """Place an overseas stock limit buy order.

        @param symbol: Overseas stock symbol.
        @param quantity: Order quantity.
        @param price: Limit price.
        @param exchange: Overseas trading exchange code.
        @returns: KIS order response or dry-run response.
        """
        return self._limit_order("BUY", symbol, quantity, price, exchange).response

    def sell_limit(self, symbol: str, quantity: int | float | Decimal, price: float, exchange: str = "NASD") -> Dict[str, Any]:
        """Place an overseas stock limit sell order.

        @param symbol: Overseas stock symbol.
        @param quantity: Order quantity.
        @param price: Limit price.
        @param exchange: Overseas trading exchange code.
        @returns: KIS order response or dry-run response.
        """
        return self._limit_order("SELL", symbol, quantity, price, exchange).response

    def _limit_order(self, side: str, symbol: str, quantity: int | float | Decimal, price: float, exchange: str) -> OrderResult:
        order_quantity = Decimal(str(quantity))
        if order_quantity <= 0:
            raise ValueError("quantity must be greater than 0")
        if price <= 0:
            raise ValueError("price must be greater than 0 for overseas limit orders")
        if exchange not in self.US_ORDER_EXCHANGES:
            raise ValueError("Only US overseas order exchanges are supported: NASD, NYSE, AMEX")

        request = OrderRequest(symbol=symbol, side=side, quantity=1, order_type="LIMIT")
        if self.client.settings.dry_run:
            response = {"dry_run": True, "symbol": symbol, "side": side, "quantity": str(order_quantity), "price": price}
            self.logger.info("[DRY-RUN US %s] symbol=%s exchange=%s price=%s quantity=%s", side, symbol, exchange, price, order_quantity)
            return OrderResult(requested=request, dry_run=True, response=response)

        self._validate_us_order_time(side)
        if order_quantity != order_quantity.to_integral_value():
            raise RuntimeError("KIS fractional overseas stock order API is not configured; live fractional order blocked.")
        payload = {
            "CANO": self.client.settings.kis_account_no,
            "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORD_QTY": str(order_quantity),
            "OVRS_ORD_UNPR": str(price),
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": "",
            "SLL_TYPE": "00" if side == "SELL" else "",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00",
        }
        tr_id = self._order_tr_id(side)
        self.logger.info("[US ORDER REQUEST] side=%s symbol=%s exchange=%s price=%s quantity=%s tr_id=%s", side, symbol, exchange, price, quantity, tr_id)
        try:
            response = self.client.post(
                "/uapi/overseas-stock/v1/trading/order",
                tr_id,
                payload,
                use_hashkey=True,
            )
        except Exception:
            self.logger.exception("[US ORDER FAILED] side=%s symbol=%s quantity=%s", side, symbol, quantity)
            raise
        self.logger.info("[US ORDER RESPONSE] side=%s symbol=%s response=%s", side, symbol, response)
        return OrderResult(requested=request, dry_run=False, response=response)

    def _order_tr_id(self, side: str) -> str:
        tr_id = "TTTT1002U" if side == "BUY" else "TTTT1006U"
        if self.client.settings.kis_is_mock:
            return f"V{tr_id[1:]}"
        return tr_id

    def _validate_us_order_time(self, side: str) -> None:
        if not self.market_hours.is_us_open(datetime.now()):
            raise RuntimeError(f"Live US order is only allowed during US regular market hours: side={side}")
