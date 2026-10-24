"""Where one reading window starts and stops, on the ad account's own days."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def yesterday(*, tzinfo: ZoneInfo, now: datetime) -> date:
    """The last day that finished in the account's own timezone."""
    return now.astimezone(tzinfo).date() - timedelta(days=1)


def start_of(day: date, tzinfo: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tzinfo)


def end_of(day: date, tzinfo: ZoneInfo) -> datetime:
    return datetime.combine(day, time.max, tzinfo=tzinfo)


__all__ = ["end_of", "start_of", "yesterday"]
