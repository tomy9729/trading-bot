from dataclasses import replace
from unittest.mock import Mock

import pytest

from src.services.trading_order_service import TradingOrderService

from tests.test_auto_trading_runner import _settings


def _live_settings():
    return replace(_settings(), dry_run=False)


def test_trading_order_service_persists_accepted_order():
    broker_order = Mock()
    broker_order.get_order_tr_id.return_value = "TTTC0802U"
    broker_order.buy_market.return_value = {"output": {"ODNO": "123"}}
    repository = Mock()
    repository.insert_order.return_value = 10
    service = TradingOrderService(_live_settings(), broker_order, repository)

    response = service.buy_market("005930", 1)

    assert response["output"]["ODNO"] == "123"
    repository.insert_order.assert_called_once_with(
        symbol="005930",
        side="BUY",
        quantity=1,
        price=0,
        order_type="MARKET",
        status="REQUESTED",
        strategy_name=None,
        raw_json={
            "symbol": "005930",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MARKET",
            "strategy_version": None,
            "applied_config": {},
        },
    )
    repository.update_order_status.assert_called_once_with(
        order_row_id=10,
        order_id="123",
        status="ACCEPTED",
        reason=None,
        raw_json={"output": {"ODNO": "123"}},
    )


def test_trading_order_service_persists_failed_order():
    broker_order = Mock()
    broker_order.get_order_tr_id.return_value = "TTTC0801U"
    broker_order.sell_market.side_effect = RuntimeError("rejected")
    repository = Mock()
    repository.insert_order.return_value = 11
    service = TradingOrderService(_live_settings(), broker_order, repository)

    with pytest.raises(RuntimeError, match="rejected"):
        service.sell_market("005930", 1)

    repository.update_order_status.assert_called_once_with(
        order_row_id=11,
        order_id=None,
        status="FAILED",
        reason="rejected",
        raw_json={"error": "rejected", "error_type": "RuntimeError"},
    )


def test_trading_order_service_does_not_persist_dry_run_order():
    broker_order = Mock()
    broker_order.buy_market.return_value = {
        "dry_run": True,
        "symbol": "005930",
        "side": "BUY",
        "quantity": 1,
    }
    repository = Mock()
    service = TradingOrderService(_settings(), broker_order, repository)

    response = service.buy_market("005930", 1)

    assert response["dry_run"] is True
    repository.insert_order.assert_not_called()
    repository.update_order_status.assert_not_called()
