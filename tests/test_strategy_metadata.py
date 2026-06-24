from dataclasses import replace

from src.config.strategy_metadata import create_strategy_metadata

from tests.test_auto_trading_runner import _bot_config


def test_strategy_metadata_is_deterministic():
    first = create_strategy_metadata(_bot_config())
    second = create_strategy_metadata(_bot_config())

    assert first == second
    assert len(first["strategy_version"]) == 12
    assert first["strategy_name"] == "test"


def test_strategy_metadata_changes_when_configuration_changes():
    bot_config = _bot_config()
    changed_strategy = replace(bot_config.strategy, volume_multiplier=3.0)
    changed_config = replace(bot_config, strategy=changed_strategy)

    assert (
        create_strategy_metadata(bot_config)["strategy_version"]
        != create_strategy_metadata(changed_config)["strategy_version"]
    )
