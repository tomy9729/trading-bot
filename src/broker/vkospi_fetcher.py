import re
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class VkospiQuote:
    source: str
    value: float
    change: float | None = None
    change_rate: float | None = None
    market_status: str | None = None


class VkospiFetcher:
    NAVER_URL = "https://polling.finance.naver.com/api/realtime"
    INVESTING_URL = "https://www.investing.com/indices/kospi-volatility"

    def __init__(self, session: requests.Session | None = None, cache_seconds: int = 30):
        self.session = session or requests.Session()
        self.cache_seconds = cache_seconds
        self._cached_quote: VkospiQuote | None = None
        self._cached_at = 0.0

    def get_current_vkospi(self) -> VkospiQuote:
        """Fetch current VKOSPI using available public web sources.

        @returns: VKOSPI quote from Naver when available, otherwise Investing.com.
        @raises RuntimeError: If every source fails.
        """
        if self._cached_quote is not None and time.monotonic() - self._cached_at < self.cache_seconds:
            return self._cached_quote

        errors = []
        for source in (self._get_naver_ksvkospi, self._get_naver_vkospi, self._get_investing):
            try:
                quote = source()
                self._cached_quote = quote
                self._cached_at = time.monotonic()
                return quote
            except RuntimeError as exc:
                errors.append(str(exc))
        raise RuntimeError(f"VKOSPI fetch failed: {'; '.join(errors)}")

    def _get_naver_ksvkospi(self) -> VkospiQuote:
        return self._get_naver("KSVKOSPI")

    def _get_naver_vkospi(self) -> VkospiQuote:
        return self._get_naver("VKOSPI")

    def _get_naver(self, code: str) -> VkospiQuote:
        data = self._request_json(self.NAVER_URL, params={"query": f"SERVICE_INDEX:{code}"})
        for area in data.get("result", {}).get("areas", []):
            for row in area.get("datas", []):
                if row.get("cd") == code:
                    return VkospiQuote(
                        source=f"naver:{code}",
                        value=_naver_number(row.get("nv")),
                        change=_naver_number(row["cv"]) if "cv" in row else None,
                        change_rate=_to_float(row["cr"]) if "cr" in row else None,
                        market_status=str(row.get("ms")) if row.get("ms") is not None else None,
                    )
        raise RuntimeError(f"Naver VKOSPI code not found: {code}")

    def _get_investing(self) -> VkospiQuote:
        response = self._request(self.INVESTING_URL)
        html = response.text
        match = re.search(r'data-test="instrument-price-last">([0-9,.]+)<', html)
        if match is None:
            match = re.search(r'"last":([0-9.]+),"changePcr":([-0-9.]+),"change":([-0-9.]+)', html)
        if match is None:
            raise RuntimeError("Investing VKOSPI price not found")
        if len(match.groups()) == 1:
            return VkospiQuote(source="investing", value=_to_float(match.group(1)))
        return VkospiQuote(
            source="investing",
            value=_to_float(match.group(1)),
            change_rate=_to_float(match.group(2)),
            change=_to_float(match.group(3)),
        )

    def _request_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        response = self._request(url, params=params)
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected JSON response from {url}")
        return data

    def _request(self, url: str, params: dict[str, str] | None = None) -> requests.Response:
        last_error = None
        for _ in range(2):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=5,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
        raise RuntimeError(f"Request failed: {url}: {last_error}")


def _naver_number(value: Any) -> float:
    return _to_float(value) / 100


def _to_float(value: Any) -> float:
    if value is None:
        raise RuntimeError("Numeric value is missing")
    return float(str(value).replace(",", ""))
