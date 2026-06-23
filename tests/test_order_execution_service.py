from datetime import datetime
from unittest.mock import Mock

from src.broker.kis_client import KisApiError
from src.domain.position import Position
from src.runner.auto_trading_state import AutoTradingState
from src.services.order_execution_service import OrderExecutionService

from tests.test_auto_trading_runner import _bot_config, _settings


def _service(order=None, account_service=None, activate_safe_mode=None):
    return OrderExecutionService(
        _settings(),
        _bot_config(),
        order or Mock(),
        account_service or Mock(),
        Mock(return_value="삼성전자"),
        Mock(return_value={"market": "KR"}),
        Mock(),
        activate_safe_mode or Mock(),
        Mock(),
    )


def test_order_execution_service_places_buy_and_clears_locks():
    order = Mock()
    order.buy_market.return_value = {"dry_run": True}
    account_service = Mock()
    state = AutoTradingState()

    _service(order=order, account_service=account_service).place_buy(state, "005930", 1, 70000)

    assert state.positions["005930"].quantity == 1
    assert state.daily_entry_count_by_symbol["005930"] == 1
    assert state.pending_order_symbols == set()
    assert state.order_locked_symbols == set()
    account_service.save_account_snapshot.assert_called_once_with(state, force=True)


def test_order_execution_service_activates_safe_mode_for_unresolved_order():
    order = Mock()
    order.buy_market.side_effect = RuntimeError("unknown")
    account_service = Mock()
    account_service.reconcile_uncertain_order.return_value = False
    activate_safe_mode = Mock()
    state = AutoTradingState()

    _service(order, account_service, activate_safe_mode).place_buy(state, "005930", 1, 70000)

    activate_safe_mode.assert_called_once_with("BUY_ORDER_STATUS_UNCERTAIN", None)
    assert state.order_locked_symbols == set()


def test_order_execution_service_does_not_reconcile_definitive_rejection():
    order = Mock()
    order.buy_market.side_effect = KisApiError(
        "TTTC0802U",
        200,
        {"rt_cd": "7", "msg_cd": "APBK0952", "msg1": "rejected"},
    )
    account_service = Mock()
    activate_safe_mode = Mock()

    _service(order, account_service, activate_safe_mode).place_buy(AutoTradingState(), "005930", 1, 70000)

    account_service.reconcile_uncertain_order.assert_not_called()
    activate_safe_mode.assert_not_called()


def test_order_execution_service_updates_partial_exit_position():
    state = AutoTradingState(
        positions={
            "005930": Position("005930", 2, 70000, datetime(2026, 6, 23, 9, 30)),
        }
    )
    service = _service()

    service.update_position_after_exit(state, "005930", 1, "FIRST_TAKE_PROFIT")

    assert state.positions["005930"].quantity == 1
    assert state.partial_profit_taken_symbols == {"005930"}
