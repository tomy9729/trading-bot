from datetime import datetime
from typing import Any

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

    def get_current_index(self, index_code: str, market_div_code: str = "U") -> dict[str, Any]:
        """Fetch the current domestic index value.

        @param index_code: KIS domestic index code.
        @param market_div_code: KIS market division code, usually U for index/upjong APIs.
        @returns: Dict with current_value, change, change_rate, and raw output.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-index-price",
            "FHPUP02100000",
            {"FID_COND_MRKT_DIV_CODE": market_div_code, "FID_INPUT_ISCD": index_code},
        )
        output = response.get("output")
        if not isinstance(output, dict) or "bstp_nmix_prpr" not in output:
            raise RuntimeError(f"KIS current index response missing output.bstp_nmix_prpr: {response}")
        current_value = _to_float(output["bstp_nmix_prpr"])
        if current_value <= 0:
            raise RuntimeError(f"KIS current index returned non-positive value: index_code={index_code}, response={response}")
        return {
            "current_value": current_value,
            "change": _to_float(output.get("bstp_nmix_prdy_vrss", 0)),
            "change_rate": _to_float(output.get("bstp_nmix_prdy_ctrt", 0)),
            "raw": output,
        }

    def get_orderbook(self, symbol: str) -> dict[str, Any]:
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

    def get_minute_chart(self, symbol: str) -> list[dict[str, Any]]:
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

    def get_time_index_chart(
        self,
        index_code: str,
        interval_seconds: str = "60",
        market_div_code: str = "U",
    ) -> list[dict[str, Any]]:
        """Fetch domestic index intraday chart rows.

        @param index_code: KIS domestic index code.
        @param interval_seconds: Aggregation unit such as 30, 60, 600, or 3600.
        @param market_div_code: KIS market division code, usually U for index/upjong APIs.
        @returns: KIS index intraday chart rows.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-indexchartprice",
            "FHKUP03500200",
            {
                "FID_COND_MRKT_DIV_CODE": market_div_code,
                "FID_INPUT_ISCD": index_code,
                "FID_INPUT_HOUR_1": interval_seconds,
                "FID_PW_DATA_INCU_YN": "Y",
                "FID_ETC_CLS_CODE": "0",
            },
        )
        return _get_non_empty_output2(response, f"KIS time index chart returned no rows: index_code={index_code}")

    def get_daily_index_chart(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
        market_div_code: str = "U",
    ) -> list[dict[str, Any]]:
        """Fetch domestic index daily chart rows.

        @param index_code: KIS domestic index code.
        @param start_date: Start date as YYYYMMDD.
        @param end_date: End date as YYYYMMDD.
        @param market_div_code: KIS market division code, usually U for index/upjong APIs.
        @returns: KIS index daily chart rows.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            "FHKUP03500100",
            {
                "FID_COND_MRKT_DIV_CODE": market_div_code,
                "FID_INPUT_ISCD": index_code,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",
            },
        )
        return _get_non_empty_output2(response, f"KIS daily index chart returned no rows: index_code={index_code}")

    def get_trading_value_rank(self, limit: int = 50) -> list[dict[str, Any]]:
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


def _to_float(value: Any) -> float:
    if value is None:
        raise RuntimeError("KIS numeric value is missing")
    if value == "":
        return 0.0
    return float(str(value).replace(",", ""))


def _get_non_empty_output2(response: dict[str, Any], message: str) -> list[dict[str, Any]]:
    output = response.get("output2")
    if not isinstance(output, list) or not output:
        raise RuntimeError(f"{message}, response={response}")
    return output
