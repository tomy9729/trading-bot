import hashlib
import json
from dataclasses import asdict
from typing import Any

from src.config.bot_config import BotConfig


def create_strategy_metadata(bot_config: BotConfig) -> dict[str, Any]:
    """Create deterministic strategy metadata for operational traceability.

    @param bot_config: Loaded bot configuration.
    @returns: Strategy name, version hash, and applied configuration.
    """
    applied_config = {
        "strategy": asdict(bot_config.strategy),
        "risk": asdict(bot_config.risk),
        "cost": asdict(bot_config.cost),
        "korea": asdict(bot_config.korea),
        "watchlist": asdict(bot_config.watchlist),
    }
    canonical_json = json.dumps(applied_config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "strategy_name": bot_config.strategy.name,
        "strategy_version": hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:12],
        "applied_config": applied_config,
    }
