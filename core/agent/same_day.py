"""Money leaving today with nothing of its own kind to show for it.

Every other rule in this package reads finished days, and for a good
reason: a partial day dragged into an average makes every campaign look
worse every morning. The cost of that discipline is a whole day. A group
sending people to a website that cannot count them, or an advert shown ten
thousand times that nobody tapped, spends its budget before anything reads
the figures that already say so.

So this reads today, and asks one narrow question that a partial day *can*
answer: has a real part of today's money gone, to enough people, with not
one result of the kind the group was bought for? It never judges a cost,
never compares groups, and never proposes a change - the owner is told, and
stopping is their button. That is the whole of why it is safe to run on a
day that is not over.

**The bars are the owner's decision, not a measurement.** A quarter of the
day's budget, shown at least two thousand times. A group with no daily
budget of its own has no quarter, and is measured against what one result
of its kind usually costs on this account instead - three of them, gone,
with none arrived. With neither there is nothing to measure against, and
nothing is said.
"""

from dataclasses import dataclass
from typing import Final

# How much of today's budget has to be gone before a nought means anything.
BUDGET_SHARE_PCT: Final = 25

# How many times the advert has to have been shown. Below this a nought is
# a group that has barely started, whatever it has spent.
MIN_IMPRESSIONS: Final = 2_000

# For a group without a daily budget: how many usual results' worth of
# money has to be gone with none arrived.
COST_MULTIPLE: Final = 3


@dataclass(frozen=True, slots=True)
class TodayGroup:
    """One group's day so far, in the figures this question needs.

    ``results`` is the count of what the group was bought for - leads, site
    visits, conversations - already chosen by the caller, which is the layer
    that knows the goal. ``usual_cost_minor`` is what one such result costs
    on this account over its recent finished days, or ``None`` when there is
    no such history.
    """

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
