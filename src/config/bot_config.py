from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class KoreaMarketConfig:
    enabled: bool
    regular_open: str
    regular_close: str
    stop_new_buy_before_close_minutes: int
    force_sell_before_close_minutes: int
    entry_windows: tuple[tuple[str, str], ...]
    watchlist: tuple[str, ...]


@dataclass(frozen=True)
class UsWatchItem:
    symbol: str
    quote_exchange: str
    order_exchange: str


@dataclass(frozen=True)
class UsMarketConfig:
    enabled: bool
    regular_open: str
    regular_close: str
    timezone: str
    entry_start_after_open_minutes: int
    entry_stop_before_close_minutes: int
    watchlist: tuple[UsWatchItem, ...]


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    volume_multiplier: float
    breakout_window_minutes: int
    volume_lookback_minutes: int
    vwap_hold_candles: int
    max_daily_rise_percent: float
    previous_candle_max_drop_percent: float
    min_execution_strength: float
    max_spread_percent: float
    max_upper_wick_percent: float
    market_down_block_threshold_percent: float


@dataclass(frozen=True)
class RiskConfig:
    max_buy_amount_per_trade: int
    us_order_amount_krw: int
    us_total_test_capital_krw: int
    us_max_symbol_exposure_krw: int
    us_assumed_usd_krw_rate: float
    us_fee_buffer_rate: float
    us_max_buy_amount_per_trade_usd: float
    us_order_mode: str
    us_fractional_order_enabled: bool
    max_daily_loss: int
    max_daily_loss_percent: float
    max_daily_trade_count: int
    max_position_count: int
    take_profit_percent: float
    second_take_profit_percent: float
    partial_take_profit_ratio: float
    stop_loss_percent: float
    break_even_stop_percent: float
    stale_position_minutes: int
    stale_position_min_profit_percent: float
    unfilled_order_timeout_seconds: int
    reentry_cooldown_minutes: int


@dataclass(frozen=True)
class KrWatchlistConfig:
    enabled: bool
    mode: str
    top_trading_value_limit: int
    refresh_interval_seconds: int
    exclude_vi_after_minutes: int
    exclude_warning_stocks: bool
    exclude_managed_stocks: bool
    exclude_suspended_stocks: bool
    min_price: int
    max_spread_rate: float
    min_orderbook_depth: int


@dataclass(frozen=True)
class UsWatchlistConfig:
    enabled: bool
    mode: str
    base_symbols: tuple[str, ...]
    optional_symbols: tuple[str, ...]
    use_optional_symbols: bool
    max_spread_rate: float
    exclude_premarket: bool
    exclude_aftermarket: bool


@dataclass(frozen=True)
class WatchlistConfig:
    kr: KrWatchlistConfig
    us: UsWatchlistConfig


@dataclass(frozen=True)
class BotConfig:
    korea: KoreaMarketConfig
    us: UsMarketConfig
    strategy: StrategyConfig
    risk: RiskConfig
    watchlist: WatchlistConfig


def load_bot_config(path: str = "config.yaml") -> BotConfig:
    """Load non-secret trading bot configuration from YAML.

    @param path: YAML config path.
    @returns: Parsed bot config.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a mapping")
    market = _get_dict(data, "market")
    korea = _get_dict(market, "korea")
    us = _get_dict(market, "us")
    strategy = _get_dict(data, "strategy")
    risk = _get_dict(data, "risk")
    watchlist = data.get("watchlist", {})
    if not isinstance(watchlist, dict):
        raise ValueError("config.watchlist must be a mapping")
    watchlist_kr = watchlist.get("kr", {})
    watchlist_us = watchlist.get("us", {})
    if not isinstance(watchlist_kr, dict) or not isinstance(watchlist_us, dict):
        raise ValueError("config.watchlist.kr/us must be mappings")
    return BotConfig(
        korea=KoreaMarketConfig(
            enabled=bool(korea.get("enabled", True)),
            regular_open=str(korea.get("regular_open", "09:00")),
            regular_close=str(korea.get("regular_close", "15:30")),
            stop_new_buy_before_close_minutes=int(korea.get("stop_new_buy_before_close_minutes", 10)),
            force_sell_before_close_minutes=int(korea.get("force_sell_before_close_minutes", 10)),
            entry_windows=_create_entry_windows(korea.get("entry_windows", [["09:10", "11:00"], ["13:30", "14:40"]])),
            watchlist=tuple(str(symbol) for symbol in korea.get("watchlist", [])),
        ),
        us=UsMarketConfig(
            enabled=bool(us.get("enabled", False)),
            regular_open=str(us.get("regular_open", "09:30")),
            regular_close=str(us.get("regular_close", "16:00")),
            timezone=str(us.get("timezone", "America/New_York")),
            entry_start_after_open_minutes=int(us.get("entry_start_after_open_minutes", 15)),
            entry_stop_before_close_minutes=int(us.get("entry_stop_before_close_minutes", 30)),
            watchlist=tuple(_create_us_watch_item(item) for item in us.get("watchlist", [])),
        ),
        strategy=StrategyConfig(
            name=str(strategy.get("name", "vwap-volume-breakout-scalping")),
            volume_multiplier=float(strategy.get("volume_multiplier", 2.0)),
            breakout_window_minutes=int(strategy.get("breakout_window_minutes", 5)),
            volume_lookback_minutes=int(strategy.get("volume_lookback_minutes", 5)),
            vwap_hold_candles=int(strategy.get("vwap_hold_candles", 3)),
            max_daily_rise_percent=float(strategy.get("max_daily_rise_percent", 15.0)),
            previous_candle_max_drop_percent=float(strategy.get("previous_candle_max_drop_percent", -2.0)),
            min_execution_strength=float(strategy.get("min_execution_strength", 55.0)),
            max_spread_percent=float(strategy.get("max_spread_percent", 0.3)),
            max_upper_wick_percent=float(strategy.get("max_upper_wick_percent", 45.0)),
            market_down_block_threshold_percent=float(strategy.get("market_down_block_threshold_percent", -0.5)),
        ),
        risk=RiskConfig(
            max_buy_amount_per_trade=int(risk.get("max_buy_amount_per_trade", 100000)),
            us_order_amount_krw=int(risk.get("us_order_amount_krw", 20000)),
            us_total_test_capital_krw=int(risk.get("us_total_test_capital_krw", 100000)),
            us_max_symbol_exposure_krw=int(risk.get("us_max_symbol_exposure_krw", 50000)),
            us_assumed_usd_krw_rate=float(risk.get("us_assumed_usd_krw_rate", 1400.0)),
            us_fee_buffer_rate=float(risk.get("us_fee_buffer_rate", 0.005)),
            us_max_buy_amount_per_trade_usd=float(risk.get("us_max_buy_amount_per_trade_usd", 100.0)),
            us_order_mode=str(risk.get("us_order_mode", "whole_share_amount")),
            us_fractional_order_enabled=bool(risk.get("us_fractional_order_enabled", False)),
            max_daily_loss=int(risk.get("max_daily_loss", 30000)),
            max_daily_loss_percent=float(risk.get("max_daily_loss_percent", -1.5)),
            max_daily_trade_count=int(risk.get("max_daily_trade_count", 5)),
            max_position_count=int(risk.get("max_position_count", 2)),
            take_profit_percent=float(risk.get("take_profit_percent", 0.8)),
            second_take_profit_percent=float(risk.get("second_take_profit_percent", 1.7)),
            partial_take_profit_ratio=float(risk.get("partial_take_profit_ratio", 0.5)),
            stop_loss_percent=float(risk.get("stop_loss_percent", -0.7)),
            break_even_stop_percent=float(risk.get("break_even_stop_percent", 0.0)),
            stale_position_minutes=int(risk.get("stale_position_minutes", 5)),
            stale_position_min_profit_percent=float(risk.get("stale_position_min_profit_percent", 0.5)),
            unfilled_order_timeout_seconds=int(risk.get("unfilled_order_timeout_seconds", 30)),
            reentry_cooldown_minutes=int(risk.get("reentry_cooldown_minutes", 15)),
        ),
        watchlist=WatchlistConfig(
            kr=KrWatchlistConfig(
                enabled=bool(watchlist_kr.get("enabled", True)),
                mode=str(watchlist_kr.get("mode", "dynamic")),
                top_trading_value_limit=int(watchlist_kr.get("top_trading_value_limit", 50)),
                refresh_interval_seconds=int(watchlist_kr.get("refresh_interval_seconds", 180)),
                exclude_vi_after_minutes=int(watchlist_kr.get("exclude_vi_after_minutes", 10)),
                exclude_warning_stocks=bool(watchlist_kr.get("exclude_warning_stocks", True)),
                exclude_managed_stocks=bool(watchlist_kr.get("exclude_managed_stocks", True)),
                exclude_suspended_stocks=bool(watchlist_kr.get("exclude_suspended_stocks", True)),
                min_price=int(watchlist_kr.get("min_price", 1000)),
                max_spread_rate=float(watchlist_kr.get("max_spread_rate", 0.3)),
                min_orderbook_depth=int(watchlist_kr.get("min_orderbook_depth", 10000000)),
            ),
            us=UsWatchlistConfig(
                enabled=bool(watchlist_us.get("enabled", True)),
                mode=str(watchlist_us.get("mode", "static")),
                base_symbols=tuple(str(symbol) for symbol in watchlist_us.get("base_symbols", [])),
                optional_symbols=tuple(str(symbol) for symbol in watchlist_us.get("optional_symbols", [])),
                use_optional_symbols=bool(watchlist_us.get("use_optional_symbols", False)),
                max_spread_rate=float(watchlist_us.get("max_spread_rate", 0.2)),
                exclude_premarket=bool(watchlist_us.get("exclude_premarket", True)),
                exclude_aftermarket=bool(watchlist_us.get("exclude_aftermarket", True)),
            ),
        ),
    )


def _create_us_watch_item(item: Any) -> UsWatchItem:
    if isinstance(item, str):
        return UsWatchItem(symbol=item, quote_exchange="NAS", order_exchange="NASD")
    if not isinstance(item, dict):
        raise ValueError("us watchlist items must be string or mapping")
    return UsWatchItem(
        symbol=str(item["symbol"]),
        quote_exchange=str(item.get("quote_exchange", "NAS")),
        order_exchange=str(item.get("order_exchange", "NASD")),
    )


def _get_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"config.{key} must be a mapping")
    return value


def _create_entry_windows(items: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(items, list):
        raise ValueError("entry_windows must be a list")
    windows = []
    for item in items:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("entry window must be [start, end]")
        windows.append((str(item[0]), str(item[1])))
    return tuple(windows)
