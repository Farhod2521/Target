"""The one change the agent makes without asking: stopping money gone for nothing."""

from dataclasses import dataclass
from typing import Final

STOP_SHARE_PCT: Final = 50
MIN_IMPRESSIONS: Final = 1_000
MIN_LINK_CLICKS: Final = 30
USUAL_COST_MULTIPLE: Final = 3


@dataclass(frozen=True, slots=True)
class SmallBudget:
    """Below ``budget_minor`` a day, the bar is ``spend_minor`` instead."""

    budget_minor: int
    spend_minor: int


@dataclass(frozen=True, slots=True)
class Fruitless:
    """One delivering group's money and results since it was last started."""

    adset_id: str
    spend_minor: int
    results: int
    budget_minor: int
    impressions: int = 0
    link_clicks: int = 0
    usual_cost_minor: int | None = None


def enough_to_judge(group: Fruitless) -> bool:
    """Whether the group has been shown enough for nought to mean something."""
    if group.impressions >= MIN_IMPRESSIONS and group.link_clicks >= MIN_LINK_CLICKS:
        return True
    usual = group.usual_cost_minor
    return usual is not None and group.spend_minor >= usual * USUAL_COST_MULTIPLE


def must_stop(group: Fruitless, *, small: SmallBudget | None) -> bool:
    """Whether this group has spent past its bar with nothing back."""
    if group.results > 0 or group.budget_minor <= 0:
        return False
    if not enough_to_judge(group):
        return False
    if small is not None and group.budget_minor < small.budget_minor:
        return group.spend_minor > small.spend_minor
    return group.spend_minor * 100 > group.budget_minor * STOP_SHARE_PCT


__all__ = [
    "MIN_IMPRESSIONS",
    "MIN_LINK_CLICKS",
    "STOP_SHARE_PCT",
    "USUAL_COST_MULTIPLE",
    "Fruitless",
    "SmallBudget",
    "enough_to_judge",
    "must_stop",
]
