from typing import Any, Dict, List

from src.broker.kis_client import KisClient


class KisOverseasAccount:
    def __init__(self, client: KisClient):
        self.client = client

    def get_balance(self, exchange: str = "NASD", currency: str = "USD") -> List[Dict[str, Any]]:
        """Fetch overseas stock balance.

        @param exchange: Overseas trading exchange code.
        @param currency: Trading currency code.
        @returns: KIS overseas balance output list.
        """
        response = self.client.get(
            "/uapi/overseas-stock/v1/trading/inquire-balance",
            "VTTS3012R" if self.client.settings.kis_is_mock else "TTTS3012R",
            {
                "CANO": self.client.settings.kis_account_no,
                "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
                "OVRS_EXCG_CD": exchange,
                "TR_CRCY_CD": currency,
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            },
        )
        output = response.get("output1")
        if output is None:
            return []
        if isinstance(output, list):
            return output
        if isinstance(output, dict):
            return [output]
        raise RuntimeError(f"KIS overseas balance response has unexpected output1: {response}")

    def get_available_cash(self, symbol: str, price: float, exchange: str = "NASD") -> float:
        """Fetch overseas stock buyable amount.

        @param symbol: Overseas stock symbol.
        @param price: Limit price used for inquiry.
        @param exchange: Overseas trading exchange code.
        @returns: Available amount as float.
        """
        response = self.client.get(
            "/uapi/overseas-stock/v1/trading/inquire-psamount",
            "VTTS3007R" if self.client.settings.kis_is_mock else "TTTS3007R",
            {
                "CANO": self.client.settings.kis_account_no,
                "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
                "OVRS_EXCG_CD": exchange,
                "OVRS_ORD_UNPR": str(price),
                "ITEM_CD": symbol,
            },
        )
        output = response.get("output")
        if not isinstance(output, dict):
            raise RuntimeError(f"KIS overseas available cash response missing output: {response}")
        value = output.get("ord_psbl_frcr_amt") or output.get("ord_psbl_cash") or output.get("max_ord_psbl_amt") or "0"
        return float(str(value).replace(",", ""))
