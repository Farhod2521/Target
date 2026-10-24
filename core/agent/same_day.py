"""Money leaving today with nothing of its own kind to show for it."""

from dataclasses import dataclass
from typing import Final

BUDGET_SHARE_PCT: Final = 25

MIN_IMPRESSIONS: Final = 2_000

COST_MULTIPLE: Final = 3


@dataclass(frozen=True, slots=True)
class TodayGroup:
    """One group's day so far, in the figures this question needs."""

    adset_id: str
    spend_minor: int
    impressions: int
    results: int
    daily_budget_minor: int | None = None
    usual_cost_minor: int | None = None


def burning(group: TodayGroup) -> bool:
    """Whether today's money is going with nothing of its kind to show."""
    if group.results > 0 or group.spend_minor <= 0:
        return False
    if group.impressions < MIN_IMPRESSIONS:
        return False
    if group.daily_budget_minor:
        return group.spend_minor * 100 >= group.daily_budget_minor * BUDGET_SHARE_PCT
    if group.usual_cost_minor:
        return group.spend_minor >= group.usual_cost_minor * COST_MULTIPLE
    return False


__all__ = [
    "BUDGET_SHARE_PCT",
    "COST_MULTIPLE",
    "MIN_IMPRESSIONS",
    "TodayGroup",
    "burning",
]
