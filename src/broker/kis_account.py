from typing import Any, Dict, List

from src.broker.kis_client import KisClient


class KisAccount:
    def __init__(self, client: KisClient):
        self.client = client

    def get_balance(self) -> List[Dict[str, Any]]:
        """Fetch domestic stock account positions.

        @returns: KIS balance output list.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            self._balance_tr_id(),
            self._balance_params(),
        )
        output = response.get("output1")
        if not isinstance(output, list):
            raise RuntimeError(f"KIS balance response missing output1 list: {response}")
        return output

    def get_available_cash(self, symbol: str = "005930") -> int:
        """Fetch available cash for a market buy order.

        @param symbol: Six-digit domestic stock code used for inquiry.
        @returns: Available order cash as integer KRW.
        """
        params = {
            "CANO": self.client.settings.kis_account_no,
            "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
            "PDNO": symbol,
            "ORD_UNPR": "0",
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "Y",
            "OVRS_ICLD_YN": "N",
        }
        response = self.client.get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            "VTTC8908R" if self.client.settings.kis_is_mock else "TTTC8908R",
            params,
        )
        output = response.get("output")
        if not isinstance(output, dict):
            raise RuntimeError(f"KIS available cash response missing output: {response}")
        cash = output.get("ord_psbl_cash") or output.get("nrcvb_buy_amt") or "0"
        return int(str(cash).replace(",", ""))

    def _balance_tr_id(self) -> str:
        return "VTTC8434R" if self.client.settings.kis_is_mock else "TTTC8434R"

    def _balance_params(self) -> Dict[str, str]:
        return {
            "CANO": self.client.settings.kis_account_no,
            "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
