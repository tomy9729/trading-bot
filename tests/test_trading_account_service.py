from unittest.mock import Mock

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
