from src.db.query_repository import TradingQueryRepository


def get_trading_repository() -> TradingQueryRepository:
    """Create the shared read-only dashboard repository dependency.

    @returns: Repository connected to the configured trading database.
    """
    return TradingQueryRepository()
