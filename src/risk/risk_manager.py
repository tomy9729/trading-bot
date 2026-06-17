from dataclasses import dataclass, field
from datetime import time
from typing import Dict, Set

from src.config import strategy_config
from src.config.env import Settings


@dataclass
class RiskState:
    current_position_count: int = 0
    daily_loss_rate: float = 0.0
    daily_loss_amount: int = 0
    consecutive_loss_count: int = 0
    safe_mode: bool = False
    kill_switch_active: bool = False
    daily_entry_count_by_symbol: Dict[str, int] = field(default_factory=dict)
    pending_order_symbols: Set[str] = field(default_factory=set)
    order_locked_symbols: Set[str] = field(default_factory=set)
    held_symbols: Set[str] = field(default_factory=set)


class RiskManager:
    def __init__(self, settings: Settings, max_daily_entry_per_symbol: int | None = None):
        self.settings = settings
        self.max_daily_entry_per_symbol = max_daily_entry_per_symbol or strategy_config.MAX_DAILY_ENTRY_PER_SYMBOL

    def can_enter(self, symbol: str, state: RiskState) -> tuple[bool, str]:
        """Check whether a new position can be opened.

        @param symbol: Six-digit domestic stock code.
        @param state: Current risk state.
        @returns: Tuple of allowed flag and reason.
        """
        if state.kill_switch_active:
            return False, "KILL_SWITCH_ACTIVE"
        if state.safe_mode:
            return False, "SAFE_MODE_ACTIVE"
        if symbol in state.order_locked_symbols:
            return False, "ORDER_LOCKED"
        if symbol in state.pending_order_symbols:
            return False, "PENDING_ORDER_EXISTS"
        if symbol in state.held_symbols:
            return False, "ALREADY_HELD_SYMBOL"
        if state.current_position_count >= self.settings.max_position_count:
            return False, "MAX_POSITION_COUNT_REACHED"
        if state.daily_loss_rate <= self.settings.daily_max_loss_rate:
            return False, "DAILY_MAX_LOSS_RATE_REACHED"
        if state.daily_loss_amount >= self.settings.daily_max_loss_amount:
            return False, "DAILY_MAX_LOSS_AMOUNT_REACHED"
        if state.consecutive_loss_count >= strategy_config.MAX_CONSECUTIVE_LOSS_COUNT:
            return False, "MAX_CONSECUTIVE_LOSS_COUNT_REACHED"
        entry_count = state.daily_entry_count_by_symbol.get(symbol, 0)
        if entry_count >= self.max_daily_entry_per_symbol:
            return False, "MAX_DAILY_ENTRY_PER_SYMBOL_REACHED"
        return True, "OK"

    def is_force_exit_time(self, current_time: time) -> bool:
        """Check whether current time is at or after force-exit time.

        @param current_time: Current local market time.
        @returns: True when positions should be force-exited.
        """
        return current_time >= _parse_time(strategy_config.FORCE_EXIT_TIME)


def _parse_time(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))
