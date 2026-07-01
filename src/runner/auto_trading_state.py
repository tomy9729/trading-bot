from dataclasses import dataclass, field
from datetime import datetime

from src.domain.position import Position


@dataclass
class AutoTradingState:
    positions: dict[str, Position] = field(default_factory=dict)
    daily_entry_count_by_symbol: dict[str, int] = field(default_factory=dict)
    pending_order_symbols: set[str] = field(default_factory=set)
    pending_buy_symbols: set[str] = field(default_factory=set)
    pending_sell_symbols: set[str] = field(default_factory=set)
    order_locked_symbols: set[str] = field(default_factory=set)
    partial_profit_taken_symbols: set[str] = field(default_factory=set)
    last_exit_at_by_symbol: dict[str, datetime] = field(default_factory=dict)
    daily_loss_amount: int = 0
    consecutive_loss_count: int = 0
    daily_realized_pnl: int = 0
    safe_mode: bool = False
    kill_switch_reasons: set[str] = field(default_factory=set)
    startup_recovered: bool = False
