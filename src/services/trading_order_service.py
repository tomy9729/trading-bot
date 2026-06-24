from typing import Any

from src.broker.kis_order import KisOrder
from src.config.env import Settings
from src.db.repository import TradingRepository
from src.logs.trade_logger import write_trade_event


class TradingOrderService:
    def __init__(
        self,
        settings: Settings,
        broker_order: KisOrder,
        trade_repository: TradingRepository | None = None,
        strategy_name: str | None = None,
        strategy_version: str | None = None,
        applied_config: dict[str, Any] | None = None,
    ):
        """Create an order service that coordinates broker calls and persistence.

        @param settings: Runtime settings.
        @param broker_order: Pure KIS order API wrapper.
        @param trade_repository: Optional trading repository.
        @param strategy_name: Active strategy name.
        @param strategy_version: Deterministic active strategy version.
        @param applied_config: Active operational configuration.
        """
        self.settings = settings
        self.broker_order = broker_order
        self.trade_repository = trade_repository
        self.strategy_name = strategy_name
        self.strategy_version = strategy_version
        self.applied_config = applied_config or {}

    def buy_market(self, symbol: str, quantity: int) -> dict[str, Any]:
        """Place and persist a domestic market buy order.

        @param symbol: Six-digit domestic stock code.
        @param quantity: Order quantity.
        @returns: KIS order response or dry-run response.
        """
        return self._market_order("BUY", symbol, quantity)

    def sell_market(self, symbol: str, quantity: int) -> dict[str, Any]:
        """Place and persist a domestic market sell order.

        @param symbol: Six-digit domestic stock code.
        @param quantity: Order quantity.
        @returns: KIS order response or dry-run response.
        """
        return self._market_order("SELL", symbol, quantity)

    def _market_order(self, side: str, symbol: str, quantity: int) -> dict[str, Any]:
        if self.settings.dry_run:
            response = self._call_broker(side, symbol, quantity)
            write_trade_event(
                "order_dry_run",
                {
                    "market": "KR",
                    "symbol": symbol,
                    "side": side,
                    "order_type": "MARKET",
                    "requested_price": 0,
                    "requested_quantity": quantity,
                    "order_status": "dry_run",
                    "order_result": response,
                    "strategy_name": self.strategy_name,
                    "strategy_version": self.strategy_version,
                    "applied_config": self.applied_config,
                    "dry_run": True,
                },
            )
            return response

        order_row_id = self._insert_order_request(side, symbol, quantity)
        tr_id = self.broker_order.get_order_tr_id(side)
        write_trade_event(
            "order_requested",
            {
                "market": "KR",
                "symbol": symbol,
                "side": side,
                "order_type": "MARKET",
                "requested_price": 0,
                "requested_quantity": quantity,
                "tr_id": tr_id,
                "strategy_name": self.strategy_name,
                "strategy_version": self.strategy_version,
                "applied_config": self.applied_config,
                "dry_run": False,
            },
        )
        try:
            response = self._call_broker(side, symbol, quantity)
        except Exception as exc:
            self._update_order_status(
                order_row_id,
                None,
                "FAILED",
                str(exc),
                {"error": str(exc), "error_type": exc.__class__.__name__},
            )
            write_trade_event(
                "order_failed",
                {
                    "market": "KR",
                    "symbol": symbol,
                    "side": side,
                    "order_type": "MARKET",
                    "requested_price": 0,
                    "requested_quantity": quantity,
                    "tr_id": tr_id,
                    "order_status": "failed",
                    "fail_reason": str(exc),
                    "fail_type": exc.__class__.__name__,
                    "strategy_name": self.strategy_name,
                    "strategy_version": self.strategy_version,
                    "dry_run": False,
                },
            )
            raise
        order_id = _get_order_id(response)
        self._update_order_status(order_row_id, order_id, "ACCEPTED", None, response)
        write_trade_event(
            "order_response",
            {
                "market": "KR",
                "symbol": symbol,
                "side": side,
                "order_type": "MARKET",
                "requested_price": 0,
                "requested_quantity": quantity,
                "tr_id": tr_id,
                "order_status": "accepted",
                "order_id": order_id,
                "order_result": response,
                "strategy_name": self.strategy_name,
                "strategy_version": self.strategy_version,
                "dry_run": False,
            },
        )
        return response

    def _call_broker(self, side: str, symbol: str, quantity: int) -> dict[str, Any]:
        if side == "BUY":
            return self.broker_order.buy_market(symbol, quantity)
        return self.broker_order.sell_market(symbol, quantity)

    def _insert_order_request(self, side: str, symbol: str, quantity: int) -> int | None:
        if self.trade_repository is None:
            return None
        return self.trade_repository.insert_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=0,
            order_type="MARKET",
            status="REQUESTED",
            strategy_name=self.strategy_name,
            raw_json={
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": "MARKET",
                "strategy_version": self.strategy_version,
                "applied_config": self.applied_config,
            },
        )

    def _update_order_status(
        self,
        order_row_id: int | None,
        order_id: str | None,
        status: str,
        reason: str | None,
        raw_json: dict[str, Any] | None,
    ) -> None:
        if self.trade_repository is None:
            return
        self.trade_repository.update_order_status(
            order_row_id=order_row_id,
            order_id=order_id,
            status=status,
            reason=reason,
            raw_json=raw_json,
        )


def _get_order_id(response: dict[str, Any]) -> str | None:
    output = response.get("output")
    if not isinstance(output, dict):
        return None
    value = output.get("ODNO") or output.get("odno") or output.get("SOR_ODNO")
    return str(value) if value not in (None, "") else None
