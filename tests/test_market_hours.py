from datetime import datetime
from zoneinfo import ZoneInfo

from src.runner.market_hours import MarketHours


def test_domestic_market_hours():
    hours = MarketHours()
    open_time = datetime(2026, 6, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    closed_time = datetime(2026, 6, 15, 21, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert hours.is_domestic_open(open_time) is True
    assert hours.is_domestic_open(closed_time) is False


def test_us_market_hours_uses_fixed_korea_time():
    hours = MarketHours()
    open_time = datetime(2026, 6, 15, 23, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    closed_time = datetime(2026, 6, 15, 21, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert hours.is_us_open(open_time) is True
    assert hours.is_us_open(closed_time) is False
