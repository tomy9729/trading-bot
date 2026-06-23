from unittest.mock import Mock

from src.broker.kis_client import KisClient
from src.broker.kis_order import KisOrder
from src.config.env import Settings
from src.runner.dry_run_runner import calculate_order_quantity


def _settings(dry_run: bool = True, force_quantity=None) -> Settings:
    return Settings("key", "secret", "12345678", "01", False, dry_run, force_quantity, 100000, 1, -2.0, 20000)


def test_dry_run_does_not_call_order_api():
    client = KisClient(_settings(True), Mock())
    client.post = Mock()
    result = KisOrder(client).buy_market("005930", 1)
    assert result["dry_run"] is True
    client.post.assert_not_called()


def test_live_mode_can_call_order_api():
    client = KisClient(_settings(False), Mock())
    client.post = Mock(return_value={"rt_cd": "0", "output": {"odno": "1"}})
    order = KisOrder(client)
    order._validate_market_order_time = Mock()
    result = order.buy_market("005930", 1)
    assert result["rt_cd"] == "0"
    client.post.assert_called_once()


def test_force_quantity_one_orders_one_share():
    assert calculate_order_quantity(2, 1) == 1


def test_force_quantity_above_available_quantity_blocks_order():
    assert calculate_order_quantity(1, 2) == 0


def test_zero_quantity_blocks_order():
    assert calculate_order_quantity(0, None) == 0


def test_available_quantity_is_used_without_separate_amount_limit():
    assert calculate_order_quantity(3, None) == 3
