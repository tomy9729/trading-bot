from unittest.mock import Mock, patch

from src.broker.kis_client import KisClient
from src.config.env import Settings


class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


def _settings(**kwargs) -> Settings:
    values = {
        "kis_app_key": "key",
        "kis_app_secret": "secret",
        "kis_account_no": "12345678",
        "kis_account_product_code": "01",
        "kis_is_mock": False,
        "dry_run": True,
        "force_quantity": None,
        "max_order_amount": 100000,
        "max_position_count": 1,
        "daily_max_loss_rate": -2.0,
        "daily_max_loss_amount": 20000,
        "kis_min_request_interval_seconds": 0.0,
        "kis_rate_limit_retry_seconds": 0.1,
        "kis_rate_limit_max_attempts": 3,
    }
    values.update(kwargs)
    return Settings(**values)


def test_kis_client_retries_egw00215_rate_limit():
    session = Mock()
    session.request.side_effect = [
        FakeResponse(500, {"rt_cd": "1", "msg_cd": "EGW00215"}),
        FakeResponse(200, {"rt_cd": "0", "output": {"ok": True}}),
    ]
    client = KisClient(_settings(), session)
    client.auth.get_access_token = Mock(return_value="token")

    with patch("src.broker.kis_client.time.sleep") as sleep:
        result = client.get("/path", "TRID", {})

    assert result["output"]["ok"] is True
    assert session.request.call_count == 2
    sleep.assert_called_once_with(0.1)


def test_kis_client_throttles_between_requests():
    session = Mock()
    session.request.return_value = FakeResponse(200, {"rt_cd": "0"})
    client = KisClient(_settings(kis_min_request_interval_seconds=0.5), session)
    client.auth.get_access_token = Mock(return_value="token")

    with patch("src.broker.kis_client.time.monotonic", side_effect=[100.0, 100.0, 100.1, 100.5]):
        with patch("src.broker.kis_client.time.sleep") as sleep:
            client.get("/path", "TRID", {})
            client.get("/path", "TRID", {})

    sleep.assert_called_once_with(0.4000000000000057)


def test_kis_client_refreshes_token_after_auth_error():
    session = Mock()
    session.request.side_effect = [
        FakeResponse(401, {"rt_cd": "1", "msg_cd": "EGW00123"}),
        FakeResponse(200, {"rt_cd": "0", "output": {"ok": True}}),
    ]
    client = KisClient(_settings(), session)
    client.auth.get_access_token = Mock(side_effect=["expired-token", "fresh-token"])
    client.auth.invalidate_access_token = Mock()

    result = client.get("/path", "TRID", {})

    assert result["output"]["ok"] is True
    assert session.request.call_count == 2
    client.auth.invalidate_access_token.assert_called_once()
    assert session.request.call_args_list[0].kwargs["headers"]["authorization"] == "Bearer expired-token"
    assert session.request.call_args_list[1].kwargs["headers"]["authorization"] == "Bearer fresh-token"
