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
of its kind usually costs on this account instead.

**And never before there is enough to judge by** - the brief's rule every
verdict shares, see :mod:`core.agent.sufficiency`: three results' usual
price gone today. Where nothing has a usual price yet, the showings above
stand in for it - an advert shown nine thousand times that nobody tapped is
the case this exists for, and a bar on clicks would never reach it.
"""

from dataclasses import dataclass
from typing import Final

from core.agent.sufficiency import enough_spent

# How much of today's budget has to be gone before a nought means anything.
BUDGET_SHARE_PCT: Final = 25

# How many times the advert has to have been shown. Below this a nought is
# a group that has barely started, whatever it has spent.
MIN_IMPRESSIONS: Final = 2_000


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
    usual = group.usual_cost_minor
    if usual and not enough_spent(
        spend_minor=group.spend_minor, usual_cost_minor=usual
    ):
        return False
    if group.daily_budget_minor:
        return group.spend_minor * 100 >= group.daily_budget_minor * BUDGET_SHARE_PCT
    # No budget of its own: the three results' worth above is the bar.
    return usual is not None


__all__ = [
    "BUDGET_SHARE_PCT",
    "MIN_IMPRESSIONS",
    "TodayGroup",
    "burning",
]
