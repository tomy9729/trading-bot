from unittest.mock import Mock

from src.broker.kis_account import KisAccount


def test_get_today_executions_accepts_empty_output1():
    client = Mock()
    client.get.return_value = {
        "output1": [],
        "output2": {
            "tot_ord_qty": "0",
            "tot_ccld_qty": "0",
        },
        "rt_cd": "0",
        "msg_cd": "KIOK0560",
    }

    account = KisAccount(client)

    assert account.get_today_executions() == []


def test_get_available_buy_quantity_uses_kis_max_buy_quantity():
    client = Mock()
    client.settings.kis_account_no = "12345678"
    client.settings.kis_account_product_code = "01"
    client.settings.kis_is_mock = False
    client.get.return_value = {
        "output": {
            "ord_psbl_cash": "496098",
            "psbl_qty_calc_unpr": "274500",
            "max_buy_qty": "1",
        },
        "rt_cd": "0",
    }

    account = KisAccount(client)

    assert account.get_available_buy_quantity("066570") == 1


def test_get_account_summary_returns_first_output2_row():
    client = Mock()
    client.get.return_value = {
        "output1": [],
        "output2": [{"dnca_tot_amt": "504680", "tot_evlu_amt": "496333"}],
        "rt_cd": "0",
    }

    account = KisAccount(client)

    assert account.get_account_summary() == {
        "dnca_tot_amt": "504680",
        "tot_evlu_amt": "496333",
    }


def test_get_daily_realized_pnl_uses_kis_total_realized_profit():
    client = Mock()
    client.settings.kis_account_no = "12345678"
    client.settings.kis_account_product_code = "01"
    client.settings.kis_is_mock = False
    client.get.return_value = {
        "output1": [{"rlzt_pfls": "-4752"}],
        "output2": {
            "tot_rlzt_pfls": "-4752",
            "tot_pftrt": "-0.95",
        },
        "rt_cd": "0",
    }

    account = KisAccount(client)

    assert account.get_daily_realized_pnl() == -4752
    assert client.get.call_args.args[0] == (
        "/uapi/domestic-stock/v1/trading/inquire-period-trade-profit"
    )
    assert client.get.call_args.args[1] == "TTTC8715R"
