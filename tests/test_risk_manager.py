from datetime import time

from src.config.env import Settings
from src.risk.risk_manager import RiskManager, RiskState


def _manager() -> RiskManager:
    settings = Settings("key", "secret", "12345678", "01", False, True, None, 100000, 1, -2.0, 20000)
    return RiskManager(settings)


def test_blocks_duplicate_pending_order():
    allowed, reason = _manager().can_enter("005930", RiskState(pending_order_symbols={"005930"}))
    assert allowed is False
    assert reason == "PENDING_ORDER_EXISTS"


def test_blocks_max_position_count():
    allowed, reason = _manager().can_enter("005930", RiskState(current_position_count=1))
    assert allowed is False
    assert reason == "MAX_POSITION_COUNT_REACHED"


def test_blocks_consecutive_losses():
    allowed, reason = _manager().can_enter("005930", RiskState(consecutive_loss_count=3))
    assert allowed is False
    assert reason == "MAX_CONSECUTIVE_LOSS_COUNT_REACHED"


def test_detects_force_exit_time():
    assert _manager().is_force_exit_time(time(15, 15)) is True
    assert _manager().is_force_exit_time(time(15, 14)) is False
