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


def test_allows_entry_when_daily_loss_limit_is_disabled():
    manager = RiskManager(_manager().settings, enforce_daily_loss_limit=False)

    allowed, reason = manager.can_enter(
        "005930",
        RiskState(daily_loss_rate=-10.0, daily_loss_amount=100000),
    )

    assert allowed is True
    assert reason == "OK"


def test_blocks_safe_mode_and_kill_switch():
    allowed, reason = _manager().can_enter("005930", RiskState(safe_mode=True))
    assert allowed is False
    assert reason == "SAFE_MODE_ACTIVE"

    allowed, reason = _manager().can_enter("005930", RiskState(kill_switch_active=True))
    assert allowed is False
    assert reason == "KILL_SWITCH_ACTIVE"


def test_blocks_order_locked_symbol():
    allowed, reason = _manager().can_enter("005930", RiskState(order_locked_symbols={"005930"}))
    assert allowed is False
    assert reason == "ORDER_LOCKED"


def test_detects_force_exit_time():
    assert _manager().is_force_exit_time(time(15, 15)) is True
    assert _manager().is_force_exit_time(time(15, 14)) is False
