import time
from typing import Any

import requests

from src.broker.kis_auth import KisAuth
from src.config.env import Settings
from src.logs.trade_logger import get_trade_logger


class KisApiError(RuntimeError):
    def __init__(self, tr_id: str, status_code: int, response: dict[str, Any]):
        self.tr_id = tr_id
        self.status_code = status_code
        self.response = response
        super().__init__(f"KIS API request failed: tr_id={tr_id}, status={status_code}, response={response}")

    @property
    def is_definitive_rejection(self) -> bool:
        """Return whether KIS explicitly rejected the request.

        @returns: True when KIS returned a successful HTTP response with a non-zero result code.
        """
        return self.status_code < 400 and str(self.response.get("rt_cd", "0")) != "0"


class KisClient:
    RATE_LIMIT_ERROR_CODES = {"EGW00201", "EGW00215"}
    AUTH_ERROR_CODES = {"EGW00123", "EGW00121", "EGW00110", "EGW00111", "EGW00112"}

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.auth = KisAuth(settings, self.session)
        self.logger = get_trade_logger()
        self._last_request_at = 0.0

    def get(self, path: str, tr_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a KIS GET endpoint.

        @param path: API path beginning with /.
        @param tr_id: KIS transaction id.
        @param params: Query parameters.
        @returns: Parsed JSON response.
        """
        return self._request("GET", path, tr_id, params=params)

    def post(self, path: str, tr_id: str, payload: dict[str, Any], use_hashkey: bool = False) -> dict[str, Any]:
        """Call a KIS POST endpoint.

        @param path: API path beginning with /.
        @param tr_id: KIS transaction id.
        @param payload: JSON request payload.
        @param use_hashkey: Whether to include KIS hashkey header.
        @returns: Parsed JSON response.
        """
        headers = {}
        if use_hashkey:
            headers["hashkey"] = self.create_hashkey(payload)
        return self._request("POST", path, tr_id, payload=payload, extra_headers=headers)

    def create_hashkey(self, payload: dict[str, Any]) -> str:
        """Create a KIS hashkey for POST request bodies.

        @param payload: JSON request payload.
        @returns: Hashkey string.
        """
        url = f"{self.settings.base_url}/uapi/hashkey"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self.settings.kis_app_key,
            "appsecret": self.settings.kis_app_secret,
        }
        self._throttle_request()
        response = self.session.post(url, json=payload, headers=headers, timeout=10)
        data = _read_json(response)
        hashkey = data.get("HASH") or data.get("hash")
        if response.status_code >= 400 or not hashkey:
            raise RuntimeError(f"KIS hashkey request failed: status={response.status_code}, response={data}")
        return str(hashkey)

    def _request(
        self,
        method: str,
        path: str,
        tr_id: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.settings.base_url}{path}"

        last_response = None
        max_attempts = max(1, self.settings.kis_rate_limit_max_attempts)
        for attempt in range(1, max_attempts + 1):
            token = self.auth.get_access_token()
            headers = {
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {token}",
                "appkey": self.settings.kis_app_key,
                "appsecret": self.settings.kis_app_secret,
                "tr_id": tr_id,
                "custtype": "P",
            }
            if extra_headers:
                headers.update(extra_headers)
            self._throttle_request()
            response = self.session.request(
                method,
                url,
                params=params,
                json=payload,
                headers=headers,
                timeout=10,
            )
            data = _read_json(response)
            last_response = (response.status_code, data)
            if response.status_code < 400 and str(data.get("rt_cd", "0")) == "0":
                return data
            if self._is_auth_error(response.status_code, data):
                self.auth.invalidate_access_token()
                if attempt < max_attempts:
                    self.logger.warning("[KIS AUTH RETRY] tr_id=%s attempt=%s response=%s", tr_id, attempt, data)
                    continue
            if data.get("msg_cd") not in self.RATE_LIMIT_ERROR_CODES or attempt >= max_attempts:
                break
            wait_seconds = self.settings.kis_rate_limit_retry_seconds * attempt
            self.logger.warning(
                "[KIS RATE LIMIT] tr_id=%s attempt=%s wait_seconds=%s response=%s",
                tr_id,
                attempt,
                wait_seconds,
                data,
            )
            time.sleep(wait_seconds)

        status_code, data = last_response or (0, {})
        raise KisApiError(tr_id, status_code, data)

    def _is_auth_error(self, status_code: int, data: dict[str, Any]) -> bool:
        if status_code in {401, 403}:
            return True
        return str(data.get("msg_cd") or "") in self.AUTH_ERROR_CODES

    def _throttle_request(self) -> None:
        interval_seconds = max(0.0, self.settings.kis_min_request_interval_seconds)
        if interval_seconds <= 0:
            return
        elapsed_seconds = time.monotonic() - self._last_request_at
        wait_seconds = interval_seconds - elapsed_seconds
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        self._last_request_at = time.monotonic()


def _read_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"KIS returned non-JSON response: status={response.status_code}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"KIS returned unexpected response type: {type(data).__name__}")
    return data
