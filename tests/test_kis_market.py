from unittest.mock import Mock

import pytest

from src.broker.kis_market import KisMarket


def test_get_current_index_reads_kis_index_price():
    client = Mock()
    client.get.return_value = {
        "output": {
            "bstp_nmix_prpr": "25.34",
            "bstp_nmix_prdy_vrss": "-0.42",
            "bstp_nmix_prdy_ctrt": "-1.63",
        }
    }

    result = KisMarket(client).get_current_index("0205")

    assert result["current_value"] == 25.34
    assert result["change"] == -0.42
    assert result["change_rate"] == -1.63
    assert client.get.call_args.args[0] == "/uapi/domestic-stock/v1/quotations/inquire-index-price"
    assert client.get.call_args.args[1] == "FHPUP02100000"
    assert client.get.call_args.args[2] == {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": "0205",
    }


def test_get_current_index_rejects_zero_value():
    client = Mock()
    client.get.return_value = {"output": {"bstp_nmix_prpr": "0.00"}}

    with pytest.raises(RuntimeError, match="non-positive value"):
        KisMarket(client).get_current_index("BAD")


def test_get_time_index_chart_reads_output2():
    client = Mock()
    client.get.return_value = {"output2": [{"bstp_nmix_prpr": "25.34"}]}

    result = KisMarket(client).get_time_index_chart("0205", "30")

    assert result == [{"bstp_nmix_prpr": "25.34"}]
    assert client.get.call_args.args[0] == "/uapi/domestic-stock/v1/quotations/inquire-time-indexchartprice"
    assert client.get.call_args.args[1] == "FHKUP03500200"
    assert client.get.call_args.args[2] == {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": "0205",
        "FID_INPUT_HOUR_1": "30",
        "FID_PW_DATA_INCU_YN": "Y",
        "FID_ETC_CLS_CODE": "0",
    }


def test_get_daily_index_chart_reads_output2():
    client = Mock()
    client.get.return_value = {"output2": [{"stck_bsop_date": "20260701"}]}

    result = KisMarket(client).get_daily_index_chart("0205", "20260601", "20260701")

    assert result == [{"stck_bsop_date": "20260701"}]
    assert client.get.call_args.args[0] == "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
    assert client.get.call_args.args[1] == "FHKUP03500100"
    assert client.get.call_args.args[2] == {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": "0205",
        "FID_INPUT_DATE_1": "20260601",
        "FID_INPUT_DATE_2": "20260701",
        "FID_PERIOD_DIV_CODE": "D",
    }
