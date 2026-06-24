from src.operations.operational_validator import validate_operations


class _Repository:
    def __init__(self, orders=None, positions=None, snapshot=None):
        self.orders = orders or []
        self.positions = positions or []
        self.snapshot = snapshot

    def get_orders(self, trade_date):
        return self.orders

    def get_current_positions(self):
        return self.positions

    def get_latest_account_snapshot(self, trade_date=None):
        return self.snapshot


def test_operational_validation_passes_without_active_orders():
    result = validate_operations(
        "2026-06-23",
        _Repository(
            orders=[{"status": "FILLED"}],
            positions=[{"symbol": "005930"}],
            snapshot={"recorded_at": "2026-06-23 15:20:00", "realized_pnl_difference": 0},
        ),
    )

    assert result.passed is True
    assert result.blockers == ()


def test_operational_validation_blocks_active_and_critical_orders():
    result = validate_operations(
        "2026-06-23",
        _Repository(
            orders=[
                {"status": "OPEN"},
                {"status": "RECONCILIATION_REQUIRED"},
            ],
        ),
    )

    assert result.passed is False
    assert result.active_order_count == 1
    assert result.critical_order_count == 1


def test_operational_validation_warns_for_pnl_difference():
    result = validate_operations(
        "2026-06-23",
        _Repository(
            snapshot={"recorded_at": "2026-06-23 15:20:00", "realized_pnl_difference": -50},
        ),
    )

    assert result.passed is True
    assert "realized_pnl_difference=-50" in result.warnings
