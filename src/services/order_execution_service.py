from datetime import datetime
from typing import Any, Callable

from src.broker.kis_client import KisApiError
from src.config.bot_config import BotConfig
from src.config.env import Settings
from src.domain.order import MarketOrderGateway
from src.domain.position import Position
from src.logs.trade_logger import write_trade_event
from src.runner.auto_trading_state import AutoTradingState
from src.services.trading_account_service import TradingAccountService


class OrderExecutionService:
    def __init__(
        self,
        settings: Settings,
        bot_config: BotConfig,
        domestic_order: MarketOrderGateway,
        account_service: TradingAccountService,
        get_symbol_name: Callable[[str, str], str | None],
        event_context: Callable[..., dict[str, Any]],
        write_skip_event: Callable[..., None],
        activate_safe_mode: Callable[[str, dict | None], None],
        logger,
    ):
        """Create domestic order execution and reconciliation service.

        @param settings: Runtime settings.
        @param bot_config: Bot strategy and risk configuration.
        @param domestic_order: Order persistence and broker coordination service.
        @param account_service: Account synchronization service.
        @param get_symbol_name: Symbol-name lookup callback.
        @param event_context: Structured event context callback.
        @param write_skip_event: Skip-event callback.
        @param activate_safe_mode: Safe-mode activation callback.
        @param logger: Trade logger.
        """
        self.settings = settings
        self.bot_config = bot_config
        self.domestic_order = domestic_order
        self.account_service = account_service
        self.get_symbol_name = get_symbol_name
        self.event_context = event_context
        self.write_skip_event = write_skip_event
        self.activate_safe_mode = activate_safe_mode
        self.logger = logger

    def place_buy(self, state: AutoTradingState, symbol: str, quantity: int, price: int) -> None:
        """Place one domestic buy and update local state.

        @param state: Mutable automatic trading state.
        @param symbol: Domestic stock code.
        @param quantity: Requested quantity.
        @param price: Strategy decision price.
        @mutate: Updates order locks, entries, and positions.
        """
        if symbol in state.order_locked_symbols:
            self.logger.info("[BUY SKIP] market=KR symbol=%s reason=ORDER_LOCKED", symbol)
            self.write_skip_event("KR", symbol, self.get_symbol_name("KR", symbol), "ORDER_LOCKED")
            return
        state.order_locked_symbols.add(symbol)
        state.pending_order_symbols.add(symbol)
        try:
            response = self.domestic_order.buy_market(symbol, quantity)
            state.daily_entry_count_by_symbol[symbol] = state.daily_entry_count_by_symbol.get(symbol, 0) + 1
            state.positions[symbol] = Position(symbol=symbol, quantity=quantity, average_price=price, entry_time=datetime.now())
            self.logger.info(
                "[BUY DONE] market=KR symbol=%s name=%r entry_price=%s quantity=%s response=%s",
                symbol,
                self.get_symbol_name("KR", symbol),
                price,
                quantity,
                response,
            )
            write_trade_event(
                "order_filled",
                {
                    **self.event_context("KR", symbol, self.get_symbol_name("KR", symbol)),
                    "side": "BUY",
                    "order_type": "MARKET",
                    "decision_price": price,
                    "entry_price": price,
                    "requested_quantity": quantity,
                    "filled_quantity": None,
                    "filled_price": None,
                    "order_result": response,
                    "dry_run": self.settings.dry_run,
                },
            )
            self.account_service.save_account_snapshot(state, force=True)
        except Exception as exc:
            if isinstance(exc, KisApiError) and exc.is_definitive_rejection:
                self.logger.warning("[BUY ORDER REJECTED] market=KR symbol=%s quantity=%s error=%s", symbol, quantity, exc)
            else:
                self.logger.exception("[BUY ORDER UNCERTAIN] market=KR symbol=%s quantity=%s", symbol, quantity)
                if not self.account_service.reconcile_uncertain_order(
                    symbol,
                    "BUY",
                    exc,
                    self.get_symbol_name("KR", symbol),
                ):
                    self.activate_safe_mode("BUY_ORDER_STATUS_UNCERTAIN", None)
        finally:
            state.pending_order_symbols.discard(symbol)
            state.order_locked_symbols.discard(symbol)

    def place_exit(self, state: AutoTradingState, symbol: str, quantity: int, reason: str) -> None:
        """Place one domestic sell and update local state.

        @param state: Mutable automatic trading state.
        @param symbol: Domestic stock code.
        @param quantity: Current held quantity.
        @param reason: Exit reason.
        @mutate: Updates order locks and positions.
        """
        sell_quantity = self.get_exit_quantity(state, symbol, quantity, reason)
        if sell_quantity < 1:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=NO_SELL_QUANTITY", symbol)
            self.write_skip_event("KR", symbol, self.get_symbol_name("KR", symbol), "NO_SELL_QUANTITY")
            return
        if symbol in state.order_locked_symbols:
            self.logger.info("[SELL SKIP] market=KR symbol=%s reason=ORDER_LOCKED", symbol)
            self.write_skip_event("KR", symbol, self.get_symbol_name("KR", symbol), "ORDER_LOCKED")
            return
        state.order_locked_symbols.add(symbol)
        state.pending_order_symbols.add(symbol)
        try:
            response = self.domestic_order.sell_market(symbol, sell_quantity)
            self.update_position_after_exit(state, symbol, sell_quantity, reason)
            self.logger.info(
                "[SELL DONE] market=KR symbol=%s name=%r quantity=%s reason=%s response=%s",
                symbol,
                self.get_symbol_name("KR", symbol),
                sell_quantity,
                reason,
                response,
            )
            write_trade_event(
                "order_filled",
                {
                    **self.event_context("KR", symbol, self.get_symbol_name("KR", symbol)),
                    "side": "SELL",
                    "order_type": "MARKET",
                    "exit_reason": reason,
                    "requested_quantity": sell_quantity,
                    "filled_quantity": None,
                    "filled_price": None,
                    "order_result": response,
                    "dry_run": self.settings.dry_run,
                },
            )
            self.account_service.save_account_snapshot(state, force=True)
        except Exception as exc:
            if isinstance(exc, KisApiError) and exc.is_definitive_rejection:
                self.logger.warning("[SELL ORDER REJECTED] market=KR symbol=%s quantity=%s error=%s", symbol, sell_quantity, exc)
            else:
                self.logger.exception("[SELL ORDER UNCERTAIN] market=KR symbol=%s quantity=%s", symbol, sell_quantity)
                if not self.account_service.reconcile_uncertain_order(
                    symbol,
                    "SELL",
                    exc,
                    self.get_symbol_name("KR", symbol),
                ):
                    self.activate_safe_mode("SELL_ORDER_STATUS_UNCERTAIN", None)
        finally:
            state.pending_order_symbols.discard(symbol)
            state.order_locked_symbols.discard(symbol)

    def get_exit_quantity(self, state: AutoTradingState, symbol: str, quantity: int, reason: str) -> int:
        """Return the quantity for a full or partial exit.

        @param state: Current automatic trading state.
        @param symbol: Domestic stock code.
        @param quantity: Current held quantity.
        @param reason: Exit reason.
        @returns: Quantity to sell.
        """
        if reason == "FIRST_TAKE_PROFIT" and symbol not in state.partial_profit_taken_symbols:
            return max(1, int(quantity * self.bot_config.risk.partial_take_profit_ratio))
        return quantity

    def update_position_after_exit(
        self,
        state: AutoTradingState,
        symbol: str,
        sell_quantity: int,
        reason: str,
    ) -> None:
        """Update local position state after a successful sell.

        @param state: Mutable automatic trading state.
        @param symbol: Domestic stock code.
        @param sell_quantity: Sold quantity.
        @param reason: Exit reason.
        @mutate: Updates or removes the local position.
        """
        position = state.positions.get(symbol)
        if position is None:
            return
        remaining_quantity = position.quantity - sell_quantity
        if reason == "FIRST_TAKE_PROFIT" and remaining_quantity > 0:
            state.partial_profit_taken_symbols.add(symbol)
            state.positions[symbol] = Position(symbol, remaining_quantity, position.average_price, position.entry_time)
            return
        state.positions.pop(symbol, None)
        state.partial_profit_taken_symbols.discard(symbol)
        state.last_exit_at_by_symbol[symbol] = datetime.now()
