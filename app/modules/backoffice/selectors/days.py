"""How many days an entitlement has left, said the way a calendar says it."""

from datetime import datetime, timedelta

_LAST_INSTANT = timedelta(microseconds=1)


def days_left(*, expires_at: datetime, now: datetime) -> int:
    """Whole calendar days after today, in ``now``'s zone; 0 is today."""
    last_day = (expires_at - _LAST_INSTANT).astimezone(now.tzinfo).date()
    return max((last_day - now.date()).days, 0)
