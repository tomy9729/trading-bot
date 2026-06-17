import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


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
    vwap_entry_price_ratio: float = 1.0


@dataclass(frozen=True)
class RiskConfig:
    max_buy_amount_per_trade: int
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
class WatchlistConfig:
    kr: KrWatchlistConfig


@dataclass(frozen=True)
class BotConfig:
    korea: KoreaMarketConfig
    strategy: StrategyConfig
    risk: RiskConfig
    watchlist: WatchlistConfig


def load_bot_config(path: str = "config.yaml") -> BotConfig:
    """Load non-secret trading bot configuration from YAML.

    @param path: YAML config path.
    @returns: Parsed bot config.
    """
    load_dotenv()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a mapping")
    market = _get_dict(data, "market")
    korea = _get_dict(market, "korea")
    strategy = _get_dict(data, "strategy")
    risk = _get_dict(data, "risk")
    watchlist = data.get("watchlist", {})
    if not isinstance(watchlist, dict):
        raise ValueError("config.watchlist must be a mapping")
    watchlist_kr = watchlist.get("kr", {})
    if not isinstance(watchlist_kr, dict):
        raise ValueError("config.watchlist.kr must be a mapping")
    bot_config = BotConfig(
        korea=KoreaMarketConfig(
            enabled=bool(korea.get("enabled", True)),
            regular_open=str(korea.get("regular_open", "09:00")),
            regular_close=str(korea.get("regular_close", "15:30")),
            stop_new_buy_before_close_minutes=int(korea.get("stop_new_buy_before_close_minutes", 10)),
            force_sell_before_close_minutes=int(korea.get("force_sell_before_close_minutes", 10)),
            entry_windows=_create_entry_windows(korea.get("entry_windows", [["09:10", "11:00"], ["13:30", "14:40"]])),
            watchlist=tuple(str(symbol) for symbol in korea.get("watchlist", [])),
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
            max_upper_wick_percent=_get_float_env("MAX_UPPER_WICK_PERCENT", float(strategy.get("max_upper_wick_percent", 45.0))),
            market_down_block_threshold_percent=float(strategy.get("market_down_block_threshold_percent", -0.5)),
            vwap_entry_price_ratio=_get_positive_float_env("VWAP_ENTRY_PRICE_RATIO", 1.0),
        ),
        risk=RiskConfig(
            max_buy_amount_per_trade=int(risk.get("max_buy_amount_per_trade", 100000)),
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
        ),
    )
    validate_bot_config(bot_config)
    return bot_config


def validate_bot_config(bot_config: BotConfig) -> None:
    """Validate non-secret bot configuration.

    @param bot_config: Loaded bot config.
    @raises ValueError: If a setting can make live operation unsafe.
    """
    if bot_config.risk.max_buy_amount_per_trade <= 0:
        raise ValueError("risk.max_buy_amount_per_trade must be greater than 0")
    if bot_config.risk.max_position_count <= 0:
        raise ValueError("risk.max_position_count must be greater than 0")
    if bot_config.risk.max_daily_loss <= 0:
        raise ValueError("risk.max_daily_loss must be greater than 0")
    if bot_config.risk.max_daily_loss_percent >= 0:
        raise ValueError("risk.max_daily_loss_percent must be negative")
    if bot_config.risk.stop_loss_percent >= 0:
        raise ValueError("risk.stop_loss_percent must be negative")
    if bot_config.risk.take_profit_percent <= 0:
        raise ValueError("risk.take_profit_percent must be greater than 0")
    if bot_config.risk.second_take_profit_percent <= 0:
        raise ValueError("risk.second_take_profit_percent must be greater than 0")
    if not 0 < bot_config.risk.partial_take_profit_ratio <= 1:
        raise ValueError("risk.partial_take_profit_ratio must be greater than 0 and less than or equal to 1")
    if bot_config.risk.reentry_cooldown_minutes < 0:
        raise ValueError("risk.reentry_cooldown_minutes must be greater than or equal to 0")
    if bot_config.strategy.volume_multiplier <= 0:
        raise ValueError("strategy.volume_multiplier must be greater than 0")
    if bot_config.strategy.vwap_entry_price_ratio <= 0:
        raise ValueError("strategy.vwap_entry_price_ratio must be greater than 0")
    if bot_config.strategy.volume_lookback_minutes <= 0:
        raise ValueError("strategy.volume_lookback_minutes must be greater than 0")
    if bot_config.strategy.breakout_window_minutes <= 0:
        raise ValueError("strategy.breakout_window_minutes must be greater than 0")
    if bot_config.korea.stop_new_buy_before_close_minutes < 0:
        raise ValueError("market.korea.stop_new_buy_before_close_minutes must be greater than or equal to 0")
    if bot_config.korea.force_sell_before_close_minutes < 0:
        raise ValueError("market.korea.force_sell_before_close_minutes must be greater than or equal to 0")


def _get_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"config.{key} must be a mapping")
    return value


def _get_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return float(value)


def _get_positive_float_env(name: str, default: float) -> float:
    value = _get_float_env(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
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
