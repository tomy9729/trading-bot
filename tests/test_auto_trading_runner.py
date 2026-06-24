from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from src.config.bot_config import (
    BotConfig,
    KoreaMarketConfig,
    KrWatchlistConfig,
    RiskConfig,
    StrategyConfig,
    TradingCostConfig,
    WatchlistConfig,
)
from src.config.env import Settings
from src.broker.kis_client import KisApiError
from src.runner.auto_trading_runner import AutoTradingRunner, _is_in_entry_windows


def _settings() -> Settings:
    return Settings("key", "secret", "12345678", "01", False, True, 1, 100000, 1, -2.0, 20000)


def _bot_config() -> BotConfig:
    return BotConfig(
        korea=KoreaMarketConfig(True, "09:00", "15:30", 10, 10, (("09:10", "11:00"),), ("005930",)),
        strategy=StrategyConfig("test", 2.0, 5, 5, 2, 15.0, -2.0, 55.0, 0.3, 60.0, -0.5),
        risk=RiskConfig(
            enforce_daily_loss_limit=True,
            max_daily_loss=5000,
            max_daily_loss_percent=-1.5,
            max_daily_trade_count=5,
            max_position_count=2,
            take_profit_percent=0.8,
            second_take_profit_percent=1.7,
            partial_take_profit_ratio=0.5,
            stop_loss_percent=-0.7,
            break_even_stop_percent=0.0,
            stale_position_minutes=5,
            stale_position_min_profit_percent=0.5,
            unfilled_order_timeout_seconds=30,
            reentry_cooldown_minutes=15,
        ),
        cost=TradingCostConfig(0.015, 0.015, 0.2, 0.05),
        watchlist=WatchlistConfig(
            kr=KrWatchlistConfig(True, "dynamic", 50, 180, 10, True, True, True, 1000, 0.3, 10000000),
        ),
    )


def _minute_rows():
    rows = []
    for index, price in enumerate([1000, 1001, 1002, 1003, 1004, 1006]):
        rows.append(
            {
                "stck_bsop_date": "20260615",
                "stck_cntg_hour": f"090{index}00",
                "stck_oprc": str(price),
                "stck_hgpr": str(price + (0 if index == 5 else 1)),
                "stck_lwpr": str(price - 1),
                "stck_prpr": str(price),
                "cntg_vol": "3000" if index == 5 else "1000",
            }
        )
    return rows


def test_auto_runner_places_domestic_dry_run_buy_when_signal_is_allowed():
    market_hours = Mock()
    market_hours.korea_tz = ZoneInfo("Asia/Seoul")
    market_hours.is_domestic_open.return_value = True

    domestic_market = Mock()
    domestic_market.get_minute_chart.return_value = _minute_rows()
    domestic_market.get_current_price.return_value = 1010
    domestic_market.get_orderbook.return_value = {"spread_rate": 0.1}

    domestic_account = Mock()
    domestic_account.get_balance.return_value = []
    domestic_account.get_open_orders.return_value = []
    domestic_account.get_today_executions.return_value = []
    domestic_account.get_daily_realized_pnl.return_value = 0
    domestic_account.get_available_buy_quantity.return_value = 1

    domestic_order = Mock()
    domestic_order.buy_market.return_value = {"dry_run": True}
    watchlist_manager = Mock()
    watchlist_manager.get_symbols.return_value = ["005930"]
    watchlist_manager.is_watchable.return_value = True

    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        market_hours,
        domestic_market,
        domestic_account,
        domestic_order,
        watchlist_manager,
    )
    runner._is_domestic_new_buy_blocked = Mock(return_value=False)

    runner.run_once()

    domestic_order.buy_market.assert_called_once_with("005930", 1)


def test_auto_runner_enters_safe_mode_after_uncertain_order_failure():
    market_hours = Mock()
    market_hours.korea_tz = ZoneInfo("Asia/Seoul")
    market_hours.is_domestic_open.return_value = True

    domestic_market = Mock()
    domestic_market.get_minute_chart.return_value = _minute_rows()
    domestic_market.get_current_price.return_value = 1010
    domestic_market.get_orderbook.return_value = {"spread_rate": 0.1}

    domestic_account = Mock()
    domestic_account.get_balance.return_value = []
    domestic_account.get_open_orders.return_value = []
    domestic_account.get_today_executions.return_value = []
    domestic_account.get_daily_realized_pnl.return_value = 0
    domestic_account.get_available_buy_quantity.return_value = 1

    domestic_order = Mock()
    domestic_order.buy_market.side_effect = [RuntimeError("order failed"), {"dry_run": True}]
    watchlist_manager = Mock()
    watchlist_manager.get_symbols.return_value = ["005930", "000660"]
    watchlist_manager.is_watchable.return_value = True

    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        market_hours,
        domestic_market,
        domestic_account,
        domestic_order,
        watchlist_manager,
    )
    runner._is_domestic_new_buy_blocked = Mock(return_value=False)

    runner.run_once()

    domestic_order.buy_market.assert_called_once_with("005930", 1)
    assert runner.state.safe_mode is True
    assert "BUY_ORDER_STATUS_UNCERTAIN" in runner.state.kill_switch_reasons


def test_auto_runner_does_not_enter_safe_mode_after_definitive_order_rejection():
    market_hours = Mock()
    market_hours.korea_tz = ZoneInfo("Asia/Seoul")
    market_hours.is_domestic_open.return_value = True

    domestic_market = Mock()
    domestic_market.get_minute_chart.return_value = _minute_rows()
    domestic_market.get_current_price.return_value = 1010
    domestic_market.get_orderbook.return_value = {"spread_rate": 0.1}

    domestic_account = Mock()
    domestic_account.get_balance.return_value = []
    domestic_account.get_open_orders.return_value = []
    domestic_account.get_today_executions.return_value = []
    domestic_account.get_daily_realized_pnl.return_value = 0
    domestic_account.get_available_buy_quantity.return_value = 1

    domestic_order = Mock()
    domestic_order.buy_market.side_effect = KisApiError(
        "TTTC0802U",
        200,
        {"rt_cd": "7", "msg_cd": "APBK0952", "msg1": "주문가능금액을 초과 했습니다"},
    )
    watchlist_manager = Mock()
    watchlist_manager.get_symbols.return_value = ["005930"]
    watchlist_manager.is_watchable.return_value = True

    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        market_hours,
        domestic_market,
        domestic_account,
        domestic_order,
        watchlist_manager,
    )
    runner._is_domestic_new_buy_blocked = Mock(return_value=False)

    runner.run_once()

    domestic_order.buy_market.assert_called_once_with("005930", 1)
    assert runner.state.safe_mode is False
    assert "BUY_ORDER_STATUS_UNCERTAIN" not in runner.state.kill_switch_reasons


def test_auto_runner_restores_position_and_blocks_duplicate_buy_after_restart():
    market_hours = Mock()
    market_hours.korea_tz = ZoneInfo("Asia/Seoul")
    market_hours.is_domestic_open.return_value = True

    domestic_market = Mock()
    domestic_market.get_minute_chart.return_value = _minute_rows()
    domestic_market.get_current_price.return_value = 1006
    domestic_market.get_orderbook.return_value = {"spread_rate": 0.1}

    domestic_account = Mock()
    domestic_account.get_balance.return_value = [{"pdno": "005930", "hldg_qty": "1", "pchs_avg_pric": "1000"}]
    domestic_account.get_open_orders.return_value = []
    domestic_account.get_today_executions.return_value = []
    domestic_account.get_daily_realized_pnl.return_value = 0

    domestic_order = Mock()
    watchlist_manager = Mock()
    watchlist_manager.get_symbols.return_value = ["005930"]
    watchlist_manager.is_watchable.return_value = True

    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        market_hours,
        domestic_market,
        domestic_account,
        domestic_order,
        watchlist_manager,
    )
    runner._is_domestic_force_sell_time = Mock(return_value=False)

    runner.run_once()

    domestic_order.buy_market.assert_not_called()
    assert "005930" in runner.state.positions


def test_auto_runner_restores_pending_buy_order_and_blocks_duplicate_buy():
    market_hours = Mock()
    market_hours.korea_tz = ZoneInfo("Asia/Seoul")
    market_hours.is_domestic_open.return_value = True

    domestic_market = Mock()
    domestic_market.get_minute_chart.return_value = _minute_rows()
    domestic_market.get_current_price.return_value = 1010
    domestic_market.get_orderbook.return_value = {"spread_rate": 0.1}

    domestic_account = Mock()
    domestic_account.get_balance.return_value = []
    domestic_account.get_open_orders.return_value = [{"pdno": "005930", "sll_buy_dvsn_cd": "02"}]
    domestic_account.get_today_executions.return_value = []
    domestic_account.get_daily_realized_pnl.return_value = 0
    domestic_account.get_available_buy_quantity.return_value = 1

    domestic_order = Mock()
    watchlist_manager = Mock()
    watchlist_manager.get_symbols.return_value = ["005930"]
    watchlist_manager.is_watchable.return_value = True

    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        market_hours,
        domestic_market,
        domestic_account,
        domestic_order,
        watchlist_manager,
    )

    runner.run_once()

    domestic_order.buy_market.assert_not_called()
    assert "005930" in runner.state.pending_buy_symbols


def test_auto_runner_enters_safe_mode_when_startup_recovery_fails():
    market_hours = Mock()
    market_hours.korea_tz = ZoneInfo("Asia/Seoul")
    market_hours.is_domestic_open.return_value = True

    domestic_account = Mock()
    domestic_account.get_balance.side_effect = RuntimeError("balance failed")

    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        market_hours,
        Mock(),
        domestic_account,
        Mock(),
        Mock(),
    )

    runner.run_once()

    assert runner.state.safe_mode is True
    assert "STARTUP_RECOVERY_FAILED" in runner.state.kill_switch_reasons


def test_auto_runner_recover_once_does_not_place_orders():
    domestic_account = Mock()
    domestic_account.get_balance.return_value = []
    domestic_account.get_open_orders.return_value = []
    domestic_account.get_today_executions.return_value = []
    domestic_order = Mock()
    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        Mock(),
        Mock(),
        domestic_account,
        domestic_order,
        Mock(),
    )

    runner.recover_once()

    assert runner.state.startup_recovered is True
    domestic_order.buy_market.assert_not_called()
    domestic_order.sell_market.assert_not_called()


def test_auto_runner_removes_positions_missing_from_latest_balance():
    trade_repository = Mock()
    runner = AutoTradingRunner(
        _settings(),
        _bot_config(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        trade_repository,
    )
    runner.state.positions = {
        "005930": Mock(),
    }

    runner._persist_position_rows(
        [
            {
                "pdno": "005930",
                "hldg_qty": "1",
                "pchs_avg_pric": "70000",
            },
            {
                "pdno": "000660",
                "hldg_qty": "0",
                "pchs_avg_pric": "120000",
            },
        ]
    )

    trade_repository.upsert_position.assert_called_once()
    trade_repository.delete_positions_except.assert_called_once_with({"005930"})


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (9, 9, False),
        (9, 10, True),
        (11, 45, True),
        (12, 10, True),
        (12, 59, True),
        (13, 0, True),
        (15, 0, True),
        (15, 1, False),
    ],
)
def test_domestic_entry_window_includes_lunch_and_end_time(hour, minute, expected):
    now = datetime(2026, 6, 18, hour, minute, tzinfo=ZoneInfo("Asia/Seoul"))

    assert _is_in_entry_windows(now, (("09:10", "15:00"),)) is expected
