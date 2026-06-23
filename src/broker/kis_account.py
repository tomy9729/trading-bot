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

    def get_account_summary(self) -> Dict[str, Any]:
        """Fetch domestic account-level asset summary.

        @returns: KIS balance output2 summary row.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            self._balance_tr_id(),
            self._balance_params(),
        )
        output = response.get("output2")
        if isinstance(output, list) and output and isinstance(output[0], dict):
            return output[0]
        if isinstance(output, dict):
            return output
        raise RuntimeError(f"KIS balance response missing output2 summary: {response}")

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

    def get_available_buy_quantity(self, symbol: str) -> int:
        """Fetch the maximum market-buy quantity allowed by KIS.

        @param symbol: Six-digit domestic stock code used for inquiry.
        @returns: Maximum quantity that can currently be submitted as a market buy.
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
            raise RuntimeError(f"KIS available quantity response missing output: {response}")
        quantity = output.get("max_buy_qty") or output.get("nrcvb_buy_qty") or "0"
        return int(str(quantity).replace(",", ""))

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Fetch domestic open orders.

        @returns: KIS open order rows.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl",
            self._open_orders_tr_id(),
            self._open_orders_params(),
        )
        output = response.get("output")
        if not isinstance(output, list):
            raise RuntimeError(f"KIS open orders response missing output list: {response}")
        return output

    def get_today_executions(self) -> List[Dict[str, Any]]:
        """Fetch today's domestic order executions.

        @returns: KIS execution rows.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            self._daily_executions_tr_id(),
            self._daily_executions_params(),
        )
        output = response.get("output1")
        if output is None:
            output = response.get("output")
        if not isinstance(output, list):
            raise RuntimeError(f"KIS daily executions response missing output list: {response}")
        return output

    def get_daily_realized_pnl(self) -> int:
        """Fetch today's realized domestic profit/loss.

        @returns: Realized profit/loss amount in KRW.
        """
        response = self.client.get(
            "/uapi/domestic-stock/v1/trading/inquire-period-trade-profit",
            self._daily_pnl_tr_id(),
            self._daily_pnl_params(),
        )
        output = response.get("output2") or response.get("output")
        if isinstance(output, list):
            return sum(_to_int(row.get("rlzt_pfls") or row.get("tot_pftrt_amt") or 0) for row in output if isinstance(row, dict))
        if isinstance(output, dict):
            return _to_int(output.get("rlzt_pfls") or output.get("tot_pftrt_amt") or output.get("realized_pnl") or 0)
        raise RuntimeError(f"KIS daily PnL response missing output: {response}")

    def _balance_tr_id(self) -> str:
        return "VTTC8434R" if self.client.settings.kis_is_mock else "TTTC8434R"

    def _open_orders_tr_id(self) -> str:
        return "VTTC8036R" if self.client.settings.kis_is_mock else "TTTC8036R"

    def _daily_executions_tr_id(self) -> str:
        return "VTTC8001R" if self.client.settings.kis_is_mock else "TTTC8001R"

    def _daily_pnl_tr_id(self) -> str:
        return "VTTC8715R" if self.client.settings.kis_is_mock else "TTTC8715R"

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

    def _open_orders_params(self) -> Dict[str, str]:
        return {
            "CANO": self.client.settings.kis_account_no,
            "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "0",
            "INQR_DVSN_2": "0",
        }

    def _daily_executions_params(self) -> Dict[str, str]:
        return {
            "CANO": self.client.settings.kis_account_no,
            "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
            "INQR_STRT_DT": _today_text(),
            "INQR_END_DT": _today_text(),
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

    def _daily_pnl_params(self) -> Dict[str, str]:
        return {
            "CANO": self.client.settings.kis_account_no,
            "ACNT_PRDT_CD": self.client.settings.kis_account_product_code,
            "SORT_DVSN": "00",
            "PDNO": "",
            "INQR_STRT_DT": _today_text(),
            "INQR_END_DT": _today_text(),
            "CBLC_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }


def _to_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(float(str(value).replace(",", "")))


def _today_text() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d")
