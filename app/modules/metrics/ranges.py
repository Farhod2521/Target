from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.metrics.constants import PERIOD_LENGTHS

CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class Range:
    since: date
    until: date
    key: str

    @property
    def days(self) -> int:
        return (self.until - self.since).days + 1


def preset_range(period: str, *, today: date) -> Range:
    days = PERIOD_LENGTHS[period]
    return Range(since=today - timedelta(days=days - 1), until=today, key=period)


__all__ = ["CUSTOM", "Range", "preset_range"]
