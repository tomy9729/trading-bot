import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_runtime_path(env_name: str, default_relative_path: str | Path) -> Path:
    """Return an absolute runtime path from an environment override or project default.

    @param env_name: Environment variable containing an optional path override.
    @param default_relative_path: Default path relative to the project root.
    @returns: Absolute runtime path.
    """
    configured_path = os.getenv(env_name)
    path = Path(configured_path) if configured_path else Path(default_relative_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def get_env_file_path() -> Path:
    """Return the dotenv file path.

    @returns: Absolute dotenv file path.
    """
    return get_runtime_path("TRADING_ENV_PATH", ".env")


def get_bot_config_path() -> Path:
    """Return the bot YAML configuration path.

    @returns: Absolute bot configuration path.
    """
    return get_runtime_path("TRADING_CONFIG_PATH", "config.yaml")


def get_database_path() -> Path:
    """Return the shared SQLite database path.

    @returns: Absolute SQLite database path.
    """
    return get_runtime_path("TRADING_DB_PATH", Path("data") / "trading.db")


def get_log_dir() -> Path:
    """Return the runtime log directory.

    @returns: Absolute log directory path.
    """
    return get_runtime_path("TRADING_LOG_DIR", "logs")


def get_report_dir() -> Path:
    """Return the generated report directory.

    @returns: Absolute report directory path.
    """
    return get_runtime_path("TRADING_REPORT_DIR", "reports")


def get_token_cache_path() -> Path:
    """Return the KIS access-token cache path.

    @returns: Absolute token cache path.
    """
    return get_runtime_path("KIS_TOKEN_CACHE_PATH", ".kis_token_cache.json")
