"""The figures a dashboard is built from, before anything formats them."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from adskit import MinorUnits

Direction = Literal["up", "down", "flat"]


@dataclass(frozen=True, slots=True)
class DayFigures:
    """One day, with everything already summed across the objects in it."""

    day: date
    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    leads: int = 0
    qualified: int = 0
    leads_reported: int = 0
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0


@dataclass(frozen=True, slots=True)
class Totals:
    """A whole range, summed. The same fields without the day."""

    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    leads: int = 0
    qualified: int = 0
    leads_reported: int = 0
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0

    @property
    def cpl_minor(self) -> MinorUnits | None:
        """What one lead cost, or nothing when there were none."""
        return cost_per(self.spend_minor, self.leads)

    @property
    def cpql_minor(self) -> MinorUnits | None:
        """What one *usable* lead cost. The figure this product exists for."""
        return cost_per(self.spend_minor, self.qualified)

    @property
    def reported_cpl_minor(self) -> MinorUnits | None:
        """What the **provider** says one lead cost, or nothing."""
        return cost_per(self.spend_minor, self.leads_reported)

    @property
    def quality_share(self) -> int:
        """What percentage of leads were worth having, rounded."""
        return share(part=self.qualified, whole=self.leads)


@dataclass(frozen=True, slots=True)
class Movement:
    """How a figure compares with the range before it."""

    percent: int = 0
    direction: Direction = "flat"
    is_good: bool = False


def cost_per(spend_minor: MinorUnits, count: int) -> MinorUnits | None:
    """Cost per one of something, or nothing when the division says nothing."""
    if count <= 0 or spend_minor <= 0:
        return None
    return MinorUnits(round(spend_minor / count))


def share(*, part: int, whole: int) -> int:
    """``part`` as a whole percentage of ``whole``. Zero divides to zero."""
    if whole <= 0:
        return 0
    return round(part / whole * 100)
