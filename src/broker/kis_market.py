from datetime import datetime
from typing import Any, Dict, List

from src.broker.kis_client import KisClient


class KisMarket:
    def __init__(self, client: KisClient):
        self.client = client

    def get_current_price(self, symbol: str) -> int:
        """Fetch the current domestic stock price.

        @param symbol: Six-digit domestic stock code.
        @returns: Current price as integer KRW.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
        )
        output = response.get("output")
        if not isinstance(output, dict) or "stck_prpr" not in output:
            raise RuntimeError(f"KIS current price response missing output.stck_prpr: {response}")
        return int(str(output["stck_prpr"]).replace(",", ""))

    def get_orderbook(self, symbol: str) -> Dict[str, Any]:
        """Fetch best bid/ask and spread rate for a domestic stock.

        @param symbol: Six-digit domestic stock code.
        @returns: Dict with best_bid, best_ask, and spread_rate.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
            "FHKST01010200",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
        )
        output = response.get("output1") or response.get("output")
        if not isinstance(output, dict):
            raise RuntimeError(f"KIS orderbook response missing output: {response}")
        best_ask = _to_int(output.get("askp1"))
        best_bid = _to_int(output.get("bidp1"))
        ask_quantity = _to_int(output.get("askp_rsqn1", 0))
        bid_quantity = _to_int(output.get("bidp_rsqn1", 0))
        midpoint = (best_ask + best_bid) / 2
        spread_rate = 0.0 if midpoint <= 0 else round(((best_ask - best_bid) / midpoint) * 100, 4)
        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_quantity": bid_quantity,
            "ask_quantity": ask_quantity,
            "depth_value": min(best_bid * bid_quantity, best_ask * ask_quantity),
            "spread_rate": spread_rate,
        }

    def get_minute_chart(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch domestic same-day minute candles.

        @param symbol: Six-digit domestic stock code.
        @returns: KIS minute candle rows.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "FHKST03010200",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_HOUR_1": datetime.now().strftime("%H%M%S"),
                "FID_PW_DATA_INCU_YN": "Y",
                "FID_ETC_CLS_CODE": "",
            },
        )
        output = response.get("output2")
        if not isinstance(output, list):
            raise RuntimeError(f"KIS minute chart response missing output2 list: {response}")
        return output

    def get_trading_value_rank(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch domestic stock ranking sorted by trading amount.

        @param limit: Maximum rows to return.
        @returns: Ranking rows from KIS volume-rank API.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            "FHPST01710000",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "3",
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "1111111111",
                "FID_INPUT_PRICE_1": "0",
                "FID_INPUT_PRICE_2": "1000000",
                "FID_VOL_CNT": "",
                "FID_INPUT_DATE_1": "",
            },
        )
        output = response.get("output")
        if not isinstance(output, list):
            raise RuntimeError(f"KIS trading value rank response missing output list: {response}")
        return output[:limit]


def _to_int(value: Any) -> int:
    if value is None:
        raise RuntimeError("KIS numeric value is missing")
    if value == "":
        return 0
    return int(str(value).replace(",", ""))
