import os
from dataclasses import dataclass

from dotenv import load_dotenv

from src.config.runtime_paths import get_env_file_path


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


def _get_optional_int(name: str) -> int | None:
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
    force_quantity: int | None
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
    load_dotenv(get_env_file_path())
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

    settings = Settings(
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
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    """Validate runtime settings before trading starts.

    @param settings: Loaded environment settings.
    @raises ValueError: If a setting can make trading unsafe.
    """
    if not settings.kis_account_no.strip():
        raise ValueError("KIS_ACCOUNT_NO must not be empty")
    if not settings.kis_account_product_code.strip():
        raise ValueError("KIS_ACCOUNT_PRODUCT_CODE must not be empty")
    if settings.force_quantity is not None and settings.force_quantity <= 0:
        raise ValueError("FORCE_QUANTITY must be greater than 0 when set")
    if settings.max_order_amount <= 0:
        raise ValueError("MAX_ORDER_AMOUNT must be greater than 0")
    if settings.max_position_count <= 0:
        raise ValueError("MAX_POSITION_COUNT must be greater than 0")
    if settings.daily_max_loss_amount <= 0:
        raise ValueError("DAILY_MAX_LOSS_AMOUNT must be greater than 0")
    if settings.daily_max_loss_rate >= 0:
        raise ValueError("DAILY_MAX_LOSS_RATE must be negative")
    if settings.kis_rate_limit_max_attempts <= 0:
        raise ValueError("KIS_RATE_LIMIT_MAX_ATTEMPTS must be greater than 0")
