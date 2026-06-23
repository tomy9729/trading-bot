import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

from src.config.env import Settings
from src.config.runtime_paths import get_token_cache_path


@dataclass
class AccessToken:
    value: str
    expires_at: datetime

    def is_valid(self) -> bool:
        return datetime.now() < self.expires_at - timedelta(minutes=5)


class KisAuth:
    def __init__(self, settings: Settings, session: Optional[requests.Session] = None):
        self.settings = settings
        self.session = session or requests.Session()
        self._token: Optional[AccessToken] = None
        self._cache_path = get_token_cache_path()

    def get_access_token(self) -> str:
        """Return a cached KIS access token or issue a new one.

        @returns: OAuth access token string.
        @raises RuntimeError: If KIS rejects the token request.
        """
        if self._token is not None and self._token.is_valid():
            return self._token.value
        cached_token = self._load_cached_token()
        if cached_token is not None and cached_token.is_valid():
            self._token = cached_token
            return cached_token.value

        url = f"{self.settings.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.settings.kis_app_key,
            "appsecret": self.settings.kis_app_secret,
        }
        response = self.session.post(url, json=payload, timeout=10)
        data = _read_json(response)
        if response.status_code >= 400 or "access_token" not in data:
            raise RuntimeError(f"KIS token request failed: status={response.status_code}, response={data}")

        expires_in = int(data.get("expires_in", 86400))
        self._token = AccessToken(
            value=str(data["access_token"]),
            expires_at=datetime.now() + timedelta(seconds=expires_in),
        )
        self._save_cached_token(self._token)
        return self._token.value

    def invalidate_access_token(self) -> None:
        """Clear the in-memory access token after an authentication failure."""
        self._token = None

    def _load_cached_token(self) -> Optional[AccessToken]:
        if not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if data.get("cache_key") != self._cache_key():
                return None
            token = AccessToken(
                value=str(data["access_token"]),
                expires_at=datetime.fromisoformat(str(data["expires_at"])),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return token

    def _save_cached_token(self, token: AccessToken) -> None:
        data = {
            "cache_key": self._cache_key(),
            "access_token": token.value,
            "expires_at": token.expires_at.isoformat(),
        }
        self._cache_path.write_text(json.dumps(data), encoding="utf-8")

    def _cache_key(self) -> str:
        raw_value = f"{self.settings.base_url}:{self.settings.kis_app_key}"
        return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def _read_json(response: requests.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"KIS returned non-JSON response: status={response.status_code}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"KIS returned unexpected response type: {type(data).__name__}")
    return data
