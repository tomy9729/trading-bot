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


def test_domestic_entry_window_is_continuous():
    bot_config = load_bot_config()

    assert bot_config.korea.entry_windows == (("09:10", "15:00"),)


def test_trading_safety_tuning_defaults_are_loaded():
    bot_config = load_bot_config()

    assert bot_config.strategy.max_breakout_chase_percent == 0.8
    assert bot_config.strategy.entry_mode == "breakout_only"
    assert bot_config.strategy.conditional_relax_min_match_rate == 1.0
    assert bot_config.strategy.relaxed_volume_multiplier == 1.75
    assert bot_config.strategy.relaxed_vwap_hold_candles == 5
    assert bot_config.strategy.pullback_enabled is False
    assert bot_config.strategy.pullback_near_vwap_percent == 0.3
    assert bot_config.risk.volume_drop_exit_min_hold_minutes == 5.0
    assert bot_config.risk.profit_protection_min_profit_amount == 0
    assert bot_config.risk.profit_protection_min_hold_minutes == 5.0
    assert bot_config.risk.profit_protection_weak_signal_count == 2
    assert bot_config.risk.profit_protection_max_execution_strength == 30.0
    assert bot_config.risk.profit_protection_min_volume_multiplier == 1.0
    assert bot_config.risk.profit_protection_upper_wick_percent == 80.0
    assert bot_config.risk.early_exit_enabled is True
    assert bot_config.risk.orderbook_exit_enabled is False
    assert bot_config.risk.weak_execution_exit_enabled is True
    assert bot_config.risk.trailing_exit_enabled is True
    assert bot_config.cost.realized_pnl_difference_tolerance == 500


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
