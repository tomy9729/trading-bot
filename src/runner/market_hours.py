from datetime import datetime, time
from zoneinfo import ZoneInfo


class MarketHours:
    def __init__(self):
        self.korea_tz = ZoneInfo("Asia/Seoul")

    def is_open(self, market: str, now: datetime | None = None) -> bool:
        """Check whether a supported market is open.

        @param market: domestic.
        @param now: Optional current datetime for tests.
        @returns: True when the selected market is open.
        """
        if market == "domestic":
            return self.is_domestic_open(now)
        raise ValueError(f"Unsupported market: {market}")

    def get_active_market(self, now: datetime | None = None) -> str | None:
        """Return the currently open market.

        @param now: Optional current datetime for tests.
        @returns: domestic or None.
        """
        if self.is_domestic_open(now):
            return "domestic"
        return None

    def is_domestic_open(self, now: datetime | None = None) -> bool:
        """Check Korea regular stock market hours.

        @param now: Optional current datetime for tests.
        @returns: True during 09:00-15:30 KST on weekdays.
        """
        current = (now or datetime.now(self.korea_tz)).astimezone(self.korea_tz)
        if current.weekday() >= 5:
            return False
        return time(9, 0) <= current.time() <= time(15, 30)

    def is_domestic_buy_open(self, now: datetime | None = None) -> bool:
        """Check Korea new-buy window.

        @param now: Optional current datetime for tests.
        @returns: True during 09:00-15:00 KST on weekdays.
        """
        current = (now or datetime.now(self.korea_tz)).astimezone(self.korea_tz)
        if current.weekday() >= 5:
            return False
        return time(9, 0) <= current.time() < time(15, 0)
