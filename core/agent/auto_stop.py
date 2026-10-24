"""The one change the agent makes without asking: stopping money gone for nothing."""

from dataclasses import dataclass
from typing import Final

STOP_SHARE_PCT: Final = 50


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


def must_stop(group: Fruitless, *, small: SmallBudget | None) -> bool:
    """Whether this group has spent past its bar with nothing back."""
    if group.results > 0 or group.budget_minor <= 0:
        return False
    if small is not None and group.budget_minor < small.budget_minor:
        return group.spend_minor > small.spend_minor
    return group.spend_minor * 100 > group.budget_minor * STOP_SHARE_PCT


__all__ = ["STOP_SHARE_PCT", "Fruitless", "SmallBudget", "must_stop"]
