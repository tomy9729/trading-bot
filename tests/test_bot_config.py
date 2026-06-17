from src.config.bot_config import load_bot_config


def test_max_upper_wick_percent_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("MAX_UPPER_WICK_PERCENT", "60.5")

    bot_config = load_bot_config()

    assert bot_config.strategy.max_upper_wick_percent == 60.5


def test_vwap_entry_price_ratio_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("VWAP_ENTRY_PRICE_RATIO", "0.998")

    bot_config = load_bot_config()

    assert bot_config.strategy.vwap_entry_price_ratio == 0.998
