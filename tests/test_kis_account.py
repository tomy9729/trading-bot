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
