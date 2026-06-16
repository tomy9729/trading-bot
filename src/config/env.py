import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value == "":
        return default
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value == "" or value is None:
        return default
    return int(value)


def _get_optional_int(name: str) -> Optional[int]:
    value = os.getenv(name)
    if value == "" or value is None:
        return None
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value == "" or value is None:
        return default
    return float(value)


@dataclass(frozen=True)
class Settings:
    kis_app_key: str
    kis_app_secret: str
    kis_account_no: str
    kis_account_product_code: str
    kis_is_mock: bool
    dry_run: bool
    force_quantity: Optional[int]
    max_order_amount: int
    max_position_count: int
    daily_max_loss_rate: float
    daily_max_loss_amount: int
    kis_min_request_interval_seconds: float = 0.5
    kis_rate_limit_retry_seconds: float = 1.0
    kis_rate_limit_max_attempts: int = 3

    @property
    def base_url(self) -> str:
        if self.kis_is_mock:
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"


def load_settings() -> Settings:
    """Load required trading-bot settings from .env and process environment.

    @returns: Immutable application settings.
    @raises ValueError: If a required KIS credential/account value is missing.
    """
    load_dotenv()
    required_names = [
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "KIS_ACCOUNT_NO",
        "KIS_ACCOUNT_PRODUCT_CODE",
    ]
    missing_names = [name for name in required_names if not os.getenv(name)]
    if missing_names:
        joined_names = ", ".join(missing_names)
        raise ValueError(f"Missing required environment variables: {joined_names}")

    return Settings(
        kis_app_key=os.environ["KIS_APP_KEY"],
        kis_app_secret=os.environ["KIS_APP_SECRET"],
        kis_account_no=os.environ["KIS_ACCOUNT_NO"],
        kis_account_product_code=os.environ["KIS_ACCOUNT_PRODUCT_CODE"],
        kis_is_mock=_get_bool("KIS_IS_MOCK", False),
        dry_run=_get_bool("DRY_RUN", True),
        force_quantity=_get_optional_int("FORCE_QUANTITY"),
        max_order_amount=_get_int("MAX_ORDER_AMOUNT", 100000),
        max_position_count=_get_int("MAX_POSITION_COUNT", 1),
        daily_max_loss_rate=_get_float("DAILY_MAX_LOSS_RATE", -2.0),
        daily_max_loss_amount=_get_int("DAILY_MAX_LOSS_AMOUNT", 20000),
        kis_min_request_interval_seconds=_get_float("KIS_MIN_REQUEST_INTERVAL_SECONDS", 0.5),
        kis_rate_limit_retry_seconds=_get_float("KIS_RATE_LIMIT_RETRY_SECONDS", 1.0),
        kis_rate_limit_max_attempts=_get_int("KIS_RATE_LIMIT_MAX_ATTEMPTS", 3),
    )
