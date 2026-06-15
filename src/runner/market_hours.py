from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


class MarketHours:
    def __init__(self):
        self.korea_tz = ZoneInfo("Asia/Seoul")
        self.new_york_tz = ZoneInfo("America/New_York")

    def is_open(self, market: str, now: datetime | None = None) -> bool:
        """Check whether a supported market is open.

        @param market: domestic, us, or auto.
        @param now: Optional current datetime for tests.
        @returns: True when the selected market is open.
        """
        if market == "auto":
            return self.is_open("domestic", now) or self.is_open("us", now)
        if market == "domestic":
            return self.is_domestic_open(now)
        if market == "us":
            return self.is_us_open(now)
        raise ValueError(f"Unsupported market: {market}")

    def get_active_market(self, now: datetime | None = None) -> str | None:
        """Return the currently open market.

        @param now: Optional current datetime for tests.
        @returns: domestic, us, or None.
        """
        if self.is_domestic_open(now):
            return "domestic"
        if self.is_us_open(now):
            return "us"
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

    def is_us_open(self, now: datetime | None = None) -> bool:
        """Check US regular stock market hours by fixed Korea time window.

        @param now: Optional current datetime for tests.
        @returns: True during 22:30-05:00 KST on US session weekdays.
        """
        current = (now or datetime.now(self.korea_tz)).astimezone(self.korea_tz)
        current_time = current.time()
        if current_time >= time(22, 30):
            session_day = current.date()
        elif current_time <= time(5, 0):
            session_day = (current - timedelta(days=1)).date()
        else:
            return False
        if session_day.weekday() >= 5:
            return False
        return current_time >= time(22, 30) or current_time <= time(5, 0)
