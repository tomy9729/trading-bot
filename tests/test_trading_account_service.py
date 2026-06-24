from unittest.mock import Mock
from datetime import datetime

from src.runner.auto_trading_state import AutoTradingState
from src.services.trading_account_service import TradingAccountService

from tests.test_auto_trading_runner import _bot_config, _settings


def _service(account=None, repository=None, activate_safe_mode=None, activate_kill_switch=None):
    account = account or Mock()
    repository = repository or Mock()

    def call_with_retries(callback, operation, symbol=None):
        return callback()

    return TradingAccountService(
        _settings(),
        _bot_config(),
        account,
        repository,
        call_with_retries,
        activate_safe_mode or Mock(),
        activate_kill_switch or Mock(),
        Mock(return_value={"market": "KR"}),
        Mock(),
    )


def test_account_service_recovers_positions_and_pending_orders():
    account = Mock()
    account.get_balance.return_value = [{"pdno": "005930", "hldg_qty": "1", "pchs_avg_pric": "70000"}]
    account.get_open_orders.return_value = [{"pdno": "000660", "sll_buy_dvsn_cd": "02"}]
    account.get_today_executions.return_value = []
    state = AutoTradingState()

    _service(account=account).recover_startup_state(state)

    assert state.startup_recovered is True
    assert state.positions["005930"].quantity == 1
    assert state.pending_buy_symbols == {"000660"}


def test_account_service_sync_positions_removes_stale_repository_rows():
    account = Mock()
    account.get_balance.return_value = [{"pdno": "005930", "hldg_qty": "1", "pchs_avg_pric": "70000"}]
    repository = Mock()
    state = AutoTradingState()

    result = _service(account=account, repository=repository).sync_positions(state)

    assert result is True
    repository.upsert_position.assert_called_once()
    repository.delete_positions_except.assert_called_once_with({"005930"})


def test_account_service_activates_safe_mode_when_balance_sync_fails():
    account = Mock()
    account.get_balance.side_effect = RuntimeError("balance failed")
    activate_safe_mode = Mock()

    result = _service(account=account, activate_safe_mode=activate_safe_mode).sync_positions(AutoTradingState())

    assert result is False
    activate_safe_mode.assert_called_once_with("BALANCE_SYNC_FAILED", None)


def test_account_service_marks_order_filled_from_execution():
    repository = Mock()
    repository.get_active_orders.return_value = [
        {
            "id": 1,
            "order_id": "123",
            "symbol": "005930",
            "side": "BUY",
            "created_at": "2026-06-23 09:30:00",
        }
    ]
    service = _service(repository=repository)

    service.reconcile_order_states(
        [],
        [{"odno": "123", "pdno": "005930", "sll_buy_dvsn_cd": "02"}],
        AutoTradingState(),
        now=datetime(2026, 6, 23, 9, 30, 10),
    )

    repository.update_order_status.assert_called_once_with(
        order_row_id=1,
        order_id="123",
        status="FILLED",
        reason=None,
    )


def test_account_service_marks_recent_open_order():
    repository = Mock()
    repository.get_active_orders.return_value = [
        {
            "id": 1,
            "order_id": "123",
            "symbol": "005930",
            "side": "BUY",
            "created_at": "2026-06-23 09:30:00",
        }
    ]
    service = _service(repository=repository)

    service.reconcile_order_states(
        [{"odno": "123", "pdno": "005930", "sll_buy_dvsn_cd": "02"}],
        [],
        AutoTradingState(),
        now=datetime(2026, 6, 23, 9, 30, 10),
    )

    repository.update_order_status.assert_called_once_with(
        order_row_id=1,
        order_id="123",
        status="OPEN",
        reason=None,
    )


def test_account_service_marks_partial_execution_as_partially_filled():
    repository = Mock()
    repository.get_active_orders.return_value = [
        {
            "id": 1,
            "order_id": "123",
            "symbol": "005930",
            "side": "BUY",
            "created_at": "2026-06-23 09:30:00",
        }
    ]
    service = _service(repository=repository)

    service.reconcile_order_states(
        [{"odno": "123", "pdno": "005930", "sll_buy_dvsn_cd": "02"}],
        [{"odno": "123", "pdno": "005930", "sll_buy_dvsn_cd": "02"}],
        AutoTradingState(),
        now=datetime(2026, 6, 23, 9, 30, 10),
    )

    repository.update_order_status.assert_called_once_with(
        order_row_id=1,
        order_id="123",
        status="PARTIALLY_FILLED",
        reason=None,
    )


def test_account_service_saves_broker_pnl_difference():
    account = Mock()
    account.get_account_summary.return_value = {
        "dnca_tot_amt": "500000",
        "scts_evlu_amt": "100000",
        "tot_evlu_amt": "600000",
        "evlu_pfls_smtl_amt": "1000",
    }
    account.get_available_cash.return_value = 490000
    account.get_daily_realized_pnl.return_value = 800
    repository = Mock()
    repository.get_cumulative_execution_cost.return_value = 150
    state = AutoTradingState(daily_realized_pnl=750)

    _service(account=account, repository=repository).save_account_snapshot(state, force=True)

    assert repository.insert_account_snapshot.call_args.kwargs["broker_daily_realized_pnl"] == 800
    assert repository.insert_account_snapshot.call_args.kwargs["realized_pnl_difference"] == -50


def test_account_service_blocks_trading_for_unfilled_timeout():
    repository = Mock()
    repository.get_active_orders.return_value = [
        {
            "id": 1,
            "order_id": "123",
            "symbol": "005930",
            "side": "BUY",
            "created_at": "2026-06-23 09:30:00",
        }
    ]
    activate_safe_mode = Mock()
    service = _service(repository=repository, activate_safe_mode=activate_safe_mode)

    service.reconcile_order_states(
        [{"odno": "123", "pdno": "005930", "sll_buy_dvsn_cd": "02"}],
        [],
        AutoTradingState(),
        now=datetime(2026, 6, 23, 9, 31),
    )

    assert repository.update_order_status.call_args.kwargs["status"] == "UNFILLED_TIMEOUT"
    activate_safe_mode.assert_called_once()
    assert activate_safe_mode.call_args.args[0] == "UNFILLED_TIMEOUT"


def test_account_service_blocks_trading_for_missing_stale_order():
    repository = Mock()
    repository.get_active_orders.return_value = [
        {
            "id": 1,
            "order_id": "123",
            "symbol": "005930",
            "side": "SELL",
            "created_at": "2026-06-23 09:30:00",
        }
    ]
    activate_safe_mode = Mock()
    service = _service(repository=repository, activate_safe_mode=activate_safe_mode)

    service.reconcile_order_states(
        [],
        [],
        AutoTradingState(),
        now=datetime(2026, 6, 23, 9, 31),
    )

    assert repository.update_order_status.call_args.kwargs["status"] == "RECONCILIATION_REQUIRED"
    assert activate_safe_mode.call_args.args[0] == "RECONCILIATION_REQUIRED"
