from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.broker.kis_market import KisMarket
from src.broker.kis_overseas_market import KisOverseasMarket
from src.config.bot_config import BotConfig, UsWatchItem
from src.logs.trade_logger import get_trade_logger
from src.runner.market_hours import MarketHours


@dataclass
class WatchlistState:
    symbols: list[str] = field(default_factory=list)
    us_items: list[UsWatchItem] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    exclude_reasons: dict[str, str] = field(default_factory=dict)
    last_refreshed_at: datetime | None = None


class WatchlistManager:
    def __init__(
        self,
        bot_config: BotConfig,
        market_hours: MarketHours,
        domestic_market: KisMarket,
        overseas_market: KisOverseasMarket,
    ):
        self.bot_config = bot_config
        self.market_hours = market_hours
        self.domestic_market = domestic_market
        self.overseas_market = overseas_market
        self.logger = get_trade_logger()
        self._states = {"KR": WatchlistState(), "US": WatchlistState()}

    def refresh(self, market: str, force: bool = False) -> None:
        """Refresh watchlist for a market.

        @param market: KR or US.
        @param force: Whether to ignore refresh interval.
        """
        if market == "KR":
            if not self._should_refresh("KR", self.bot_config.watchlist.kr.refresh_interval_seconds, force):
                return
            self._refresh_kr()
            return
        if market == "US":
            if not self._should_refresh("US", 300, force):
                return
            self._refresh_us()
            return
        raise ValueError(f"Unsupported market: {market}")

    def get_symbols(self, market: str) -> list[str]:
        """Return current watchable symbols.

        @param market: KR or US.
        @returns: Symbols.
        """
        return list(self._states[market].symbols)

    def get_us_items(self) -> list[UsWatchItem]:
        """Return current watchable US items.

        @returns: US watch items with exchanges.
        """
        return list(self._states["US"].us_items)

    def is_watchable(self, market: str, symbol: str) -> bool:
        """Check whether a symbol is currently watchable.

        @param market: KR or US.
        @param symbol: Symbol.
        @returns: True when watchable.
        """
        return symbol in self._states[market].symbols

    def get_exclude_reason(self, market: str, symbol: str) -> str | None:
        """Return exclusion reason for a symbol.

        @param market: KR or US.
        @param symbol: Symbol.
        @returns: Exclusion reason or None.
        """
        return self._states[market].exclude_reasons.get(symbol)

    def get_symbol_name(self, market: str, symbol: str) -> str | None:
        """Return a cached display name for a symbol.

        @param market: KR or US.
        @param symbol: Symbol.
        @returns: Symbol name or None when unavailable.
        """
        return self._states[market].names.get(symbol)

    def _refresh_kr(self) -> None:
        config = self.bot_config.watchlist.kr
        previous_symbols = set(self._states["KR"].symbols)
        exclude_reasons: dict[str, str] = {}
        names: dict[str, str] = {}
        if not config.enabled:
            self._states["KR"] = WatchlistState(exclude_reasons={"*": "watchlist_disabled"}, last_refreshed_at=datetime.now())
            return

        if config.mode != "dynamic":
            candidates = [{"symbol": symbol, "rank": index + 1} for index, symbol in enumerate(self.bot_config.korea.watchlist)]
        else:
            rank_rows = self.domestic_market.get_trading_value_rank(config.top_trading_value_limit)
            candidates = [_create_kr_candidate(row, index + 1) for index, row in enumerate(rank_rows)]

        symbols = []
        for candidate in candidates:
            symbol = candidate["symbol"]
            name = candidate.get("name")
            if name:
                names[symbol] = str(name)
            reason = self._get_kr_exclude_reason(symbol)
            if reason is not None:
                exclude_reasons[symbol] = reason
                self.logger.info("[WATCHLIST EXCLUDE] market=KR symbol=%s name=%r rank=%s reason=%s", symbol, name, candidate.get("rank"), reason)
                continue
            symbols.append(symbol)

        self._states["KR"] = WatchlistState(symbols=symbols, names=names, exclude_reasons=exclude_reasons, last_refreshed_at=datetime.now())
        self._log_refresh("KR", previous_symbols, symbols)

    def _refresh_us(self) -> None:
        config = self.bot_config.watchlist.us
        previous_symbols = set(self._states["US"].symbols)
        exclude_reasons: dict[str, str] = {}
        names: dict[str, str] = {}
        if not config.enabled:
            self._states["US"] = WatchlistState(exclude_reasons={"*": "watchlist_disabled"}, last_refreshed_at=datetime.now())
            return

        item_by_symbol = {item.symbol: item for item in self.bot_config.us.watchlist}
        symbols = list(config.base_symbols)
        if config.use_optional_symbols:
            symbols.extend(config.optional_symbols)

        items = []
        for symbol in dict.fromkeys(symbols):
            item = item_by_symbol.get(symbol) or UsWatchItem(symbol=symbol, quote_exchange="NAS", order_exchange="NASD")
            names[item.symbol] = item.symbol
            reason = self._get_us_exclude_reason(item)
            if reason is not None:
                exclude_reasons[symbol] = reason
                self.logger.info("[WATCHLIST EXCLUDE] market=US symbol=%s name=%r reason=%s", symbol, names[item.symbol], reason)
                continue
            items.append(item)

        self._states["US"] = WatchlistState(
            symbols=[item.symbol for item in items],
            us_items=items,
            names=names,
            exclude_reasons=exclude_reasons,
            last_refreshed_at=datetime.now(),
        )
        self._log_refresh("US", previous_symbols, [item.symbol for item in items])

    def _get_kr_exclude_reason(self, symbol: str) -> str | None:
        config = self.bot_config.watchlist.kr
        try:
            price = self.domestic_market.get_current_price(symbol)
            if price < config.min_price:
                return "low_price"
            orderbook = self.domestic_market.get_orderbook(symbol)
            if float(orderbook["spread_rate"]) > config.max_spread_rate:
                return "wide_spread"
            if int(orderbook.get("depth_value", 0)) < config.min_orderbook_depth:
                return "low_orderbook_depth"
        except Exception as exc:
            return f"watchlist_check_failed:{exc.__class__.__name__}"
        return None

    def _get_us_exclude_reason(self, item: UsWatchItem) -> str | None:
        config = self.bot_config.watchlist.us
        if config.exclude_premarket or config.exclude_aftermarket:
            if not self.market_hours.is_us_open():
                return "outside_regular_market"
        try:
            orderbook = self.overseas_market.get_orderbook(item.symbol, item.quote_exchange)
            if float(orderbook["spread_rate"]) > config.max_spread_rate:
                return "wide_spread"
        except Exception as exc:
            return f"watchlist_check_failed:{exc.__class__.__name__}"
        return None

    def _should_refresh(self, market: str, interval_seconds: int, force: bool) -> bool:
        last_refreshed_at = self._states[market].last_refreshed_at
        if force or last_refreshed_at is None:
            return True
        return datetime.now() - last_refreshed_at >= timedelta(seconds=interval_seconds)

    def _log_refresh(self, market: str, previous_symbols: set[str], symbols: list[str]) -> None:
        current_symbols = set(symbols)
        added_symbols = sorted(current_symbols - previous_symbols)
        removed_symbols = sorted(previous_symbols - current_symbols)
        self.logger.info(
            "[WATCHLIST REFRESH] market=%s count=%s added=%s removed=%s",
            market,
            len(symbols),
            added_symbols,
            removed_symbols,
        )


def _create_kr_candidate(row: dict[str, Any], rank: int) -> dict[str, Any]:
    symbol = (
        row.get("mksc_shrn_iscd")
        or row.get("stck_shrn_iscd")
        or row.get("pdno")
        or ""
    )
    name = row.get("hts_kor_isnm") or row.get("prdt_name") or row.get("stck_prdt_name") or row.get("name")
    return {"symbol": str(symbol), "name": str(name) if name not in (None, "") else None, "rank": rank, "raw": row}
