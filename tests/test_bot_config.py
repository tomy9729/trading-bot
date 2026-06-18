from dataclasses import replace

import pytest

from src.config.bot_config import load_bot_config
from src.config.env import Settings, validate_settings


def test_max_upper_wick_percent_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("MAX_UPPER_WICK_PERCENT", "60.5")

    bot_config = load_bot_config()

    assert bot_config.strategy.max_upper_wick_percent == 60.5


def test_vwap_entry_price_ratio_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("VWAP_ENTRY_PRICE_RATIO", "0.998")

    bot_config = load_bot_config()

    assert bot_config.strategy.vwap_entry_price_ratio == 0.998


def test_max_buy_amount_per_trade_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("MAX_BUY_AMOUNT_PER_TRADE", "500000")

    bot_config = load_bot_config()

    assert bot_config.risk.max_buy_amount_per_trade == 500000


def test_max_buy_amount_per_trade_env_must_be_positive(monkeypatch):
    monkeypatch.setenv("MAX_BUY_AMOUNT_PER_TRADE", "0")

    with pytest.raises(ValueError, match="MAX_BUY_AMOUNT_PER_TRADE"):
        load_bot_config()


def test_domestic_entry_window_is_continuous():
    bot_config = load_bot_config()

    assert bot_config.korea.entry_windows == (("09:10", "15:00"),)


def test_bot_config_rejects_invalid_stop_loss():
    bot_config = load_bot_config()
    invalid_config = replace(bot_config, risk=replace(bot_config.risk, stop_loss_percent=0.5))

    with pytest.raises(ValueError, match="stop_loss_percent"):
        from src.config.bot_config import validate_bot_config

        validate_bot_config(invalid_config)


def test_settings_rejects_empty_account_number():
    settings = Settings("key", "secret", "", "01", False, True, None, 100000, 1, -2.0, 20000)

    with pytest.raises(ValueError, match="KIS_ACCOUNT_NO"):
        validate_settings(settings)
