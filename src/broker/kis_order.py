from datetime import datetime, time
from typing import Any, Dict

from src.broker.kis_client import KisClient
from src.domain.order import OrderRequest, OrderResult
from src.logs.trade_logger import get_trade_logger
from src.runner.market_hours import MarketHours


class KisOrder:
    def __init__(self, client: KisClient, market_hours: MarketHours | None = None):
        self.client = client
        self.market_hours = market_hours or MarketHours()
        self.logger = get_trade_logger()

    def buy_market(self, symbol: str, quantity: int) -> Dict[str, Any]:
        """Place a domestic stock market buy order.

        @param symbol: Six-digit domestic stock code.
        @param quantity: Order quantity.
        @returns: KIS order response or dry-run response.
        """
        return self._market_order("BUY", symbol, quantity).response

    def sell_market(self, symbol: str, quantity: int) -> Dict[str, Any]:
        """Place a domestic stock market sell order.

        @param symbol: Six-digit domestic stock code.
        @param quantity: Order quantity.
        @returns: KIS order response or dry-run response.
        """
        return self._market_order("SELL", symbol, quantity).response

    def _market_order(self, side: str, symbol: str, quantity: int) -> OrderResult:
        if quantity < 1:
            raise ValueError("quantity must be greater than 0")

        request = OrderRequest(symbol=symbol, side=side, quantity=quantity)
        if self.client.settings.dry_run:
            response = {"dry_run": True, "symbol": symbol, "side": side, "quantity": quantity}
            self.logger.info("[DRY-RUN %s] symbol=%s quantity=%s", side, symbol, quantity)
            return OrderResult(requested=request, dry_run=True, response=response)

        self._validate_market_order_time(side)

        payload = {
            "CANO": self.client.settings.kis_account_no,
            "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
            "PDNO": symbol,
            "ORD_DVSN": "01",
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
        }
        tr_id = self._order_tr_id(side)
        self.logger.info("[ORDER REQUEST] side=%s symbol=%s quantity=%s tr_id=%s", side, symbol, quantity, tr_id)
        try:
            response = self.client.post(
                "/uapi/domestic-stock/v1/trading/order-cash",
                tr_id,
                payload,
                use_hashkey=True,
            )
        except Exception:
            self.logger.exception("[ORDER FAILED] side=%s symbol=%s quantity=%s", side, symbol, quantity)
            raise
        self.logger.info("[ORDER RESPONSE] side=%s symbol=%s response=%s", side, symbol, response)
        return OrderResult(requested=request, dry_run=False, response=response)

    def _order_tr_id(self, side: str) -> str:
        if self.client.settings.kis_is_mock:
            return "VTTC0802U" if side == "BUY" else "VTTC0801U"
        return "TTTC0802U" if side == "BUY" else "TTTC0801U"

    def _validate_market_order_time(self, side: str) -> None:
        now = datetime.now()
        now_time = now.time()
        if not self.market_hours.is_domestic_open(now):
            raise RuntimeError(
                f"Live market order is only allowed during regular market hours: "
                f"side={side}, current_time={now_time.strftime('%H:%M:%S')}"
            )
        if side == "BUY" and not self.market_hours.is_domestic_buy_open(now):
            raise RuntimeError(
                f"Live buy is blocked after the new-buy limit time: current_time={now_time.strftime('%H:%M:%S')}"
            )
