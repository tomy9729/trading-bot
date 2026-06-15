import time
from typing import Any, Dict, Optional

import requests

from src.broker.kis_auth import KisAuth
from src.config.env import Settings
from src.logs.trade_logger import get_trade_logger


class KisClient:
    RATE_LIMIT_ERROR_CODE = "EGW00201"

    def __init__(self, settings: Settings, session: Optional[requests.Session] = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.auth = KisAuth(settings, self.session)
        self.logger = get_trade_logger()

    def get(self, path: str, tr_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Call a KIS GET endpoint.

        @param path: API path beginning with /.
        @param tr_id: KIS transaction id.
        @param params: Query parameters.
        @returns: Parsed JSON response.
        """
        return self._request("GET", path, tr_id, params=params)

    def post(self, path: str, tr_id: str, payload: Dict[str, Any], use_hashkey: bool = False) -> Dict[str, Any]:
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

    def create_hashkey(self, payload: Dict[str, Any]) -> str:
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
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        token = self.auth.get_access_token()
        url = f"{self.settings.base_url}{path}"
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

        last_response = None
        for attempt in range(1, 4):
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
            if data.get("msg_cd") != self.RATE_LIMIT_ERROR_CODE or attempt >= 3:
                break
            wait_seconds = attempt
            self.logger.warning(
                "[KIS RATE LIMIT] tr_id=%s attempt=%s wait_seconds=%s response=%s",
                tr_id,
                attempt,
                wait_seconds,
                data,
            )
            time.sleep(wait_seconds)

        status_code, data = last_response or (0, {})
        raise RuntimeError(f"KIS API request failed: tr_id={tr_id}, status={status_code}, response={data}")


def _read_json(response: requests.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"KIS returned non-JSON response: status={response.status_code}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"KIS returned unexpected response type: {type(data).__name__}")
    return data
