from typing import Any, Dict, List

from src.broker.kis_client import KisClient


class KisOverseasMarket:
    def __init__(self, client: KisClient):
        self.client = client

    def get_current_price(self, symbol: str, exchange: str = "NAS") -> float:
        """Fetch overseas stock current execution price.

        @param symbol: Overseas stock symbol, for example AAPL.
        @param exchange: Overseas quote exchange code, for example NAS, NYS, or AMS.
        @returns: Current or delayed price.
        """
        response = self.client.get(
            "/uapi/overseas-price/v1/quotations/price",
            "HHDFS00000300",
            {"AUTH": "", "EXCD": exchange, "SYMB": symbol},
        )
        output = response.get("output")
        if not isinstance(output, dict):
            raise RuntimeError(f"KIS overseas price response missing output: {response}")
        value = output.get("last") or output.get("base") or output.get("pvol")
        if value is None:
            raise RuntimeError(f"KIS overseas price response missing price field: {response}")
        return float(str(value).replace(",", ""))

    def get_orderbook(self, symbol: str, exchange: str = "NAS") -> Dict[str, Any]:
        """Fetch overseas stock best bid/ask and spread rate.

        @param symbol: Overseas stock symbol, for example AAPL.
        @param exchange: Overseas quote exchange code, for example NAS, NYS, or AMS.
        @returns: Dict with best_bid, best_ask, and spread_rate.
        """
        response = self.client.get(
            "/uapi/overseas-price/v1/quotations/inquire-asking-price",
            "HHDFS76200100",
            {"AUTH": "", "EXCD": exchange, "SYMB": symbol},
        )
        output = response.get("output1") or response.get("output2") or response.get("output")
        if not isinstance(output, dict):
            raise RuntimeError(f"KIS overseas orderbook response missing output: {response}")
        if not _has_any(output, ("pbid1", "bidp1", "bid")) or not _has_any(output, ("pask1", "askp1", "ask")):
            last_price = _get_float(output, ("last", "base"))
            return {"best_bid": last_price, "best_ask": last_price, "spread_rate": 0.0}
        best_bid = _get_float(output, ("pbid1", "bidp1", "bid"))
        best_ask = _get_float(output, ("pask1", "askp1", "ask"))
        midpoint = (best_ask + best_bid) / 2
        spread_rate = 0.0 if midpoint <= 0 else round(((best_ask - best_bid) / midpoint) * 100, 4)
        return {"best_bid": best_bid, "best_ask": best_ask, "spread_rate": spread_rate}

    def get_minute_chart(self, symbol: str, exchange: str = "NAS", count: int = 30) -> List[Dict[str, Any]]:
        """Fetch overseas minute candles.

        @param symbol: Overseas stock symbol.
        @param exchange: Quote exchange code.
        @param count: Record count, up to 120.
        @returns: KIS overseas minute candle rows.
        """
        response = self.client.get(
            "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice",
            "HHDFS76950200",
            {
                "AUTH": "",
                "EXCD": exchange,
                "SYMB": symbol,
                "NMIN": "1",
                "PINC": "0",
                "NEXT": "",
                "NREC": str(min(max(count, 1), 120)),
                "FILL": "",
                "KEYB": "",
            },
        )
        output = response.get("output2")
        if not isinstance(output, list):
            raise RuntimeError(f"KIS overseas minute chart response missing output2 list: {response}")
        return output


def _get_float(output: Dict[str, Any], names: tuple[str, ...]) -> float:
    for name in names:
        value = output.get(name)
        if value not in (None, ""):
            return float(str(value).replace(",", ""))
    raise RuntimeError(f"KIS overseas numeric value is missing: candidates={names}, output={output}")


def _has_any(output: Dict[str, Any], names: tuple[str, ...]) -> bool:
    return any(output.get(name) not in (None, "") for name in names)
