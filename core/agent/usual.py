"""What a pair's advertising usually does: the median of its last fortnight.

**The reference a figure is read against when there is nothing beside it.**
Every comparison in ``core.agent.benchmark`` is with the pair's *other*
groups bought for the same result, and a pair with one group - the shape
most new cabinets have - has none. Its cost rules then had nothing to call
dear and stayed silent on exactly the account that most needed telling.
The same advertising's own last fourteen days are always there.

**A median of days, not a sum of them.** One day with a viral post or one
day the form broke moves a fortnight's total; it does not move the middle
day. A day that spent and brought no result has no price, and it is not
left out - it is the dearest day there was, so a fortnight where most days
brought nothing has no usual price at all rather than the price of its few
good days. That case falls back to the fortnight's pooled price, which is
still the pair's own history.

Pure arithmetic over plain values, like the rest of ``core``.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median_low
from typing import Literal

from core.agent.funnel import per_ten_thousand
from core.agent.sufficiency import enough_spent


@dataclass(frozen=True, slots=True)
class DayFigures:
    """One day of one family of groups, summed across them.

    No frequency: a person counts once a range, never once a day, so a
    day's frequency summed into a fortnight is a different number from the
    one every screen shows - see :mod:`core.agent.frequency`.
    """

    spend_minor: int = 0
    impressions: int = 0
    link_clicks: int = 0
    # The family's own results that day - leads, conversations, calls,
    # showings - counted the way ``core.agent.benchmark.count_in`` counts.
    results: int = 0
    video_impressions: int = 0
    video_views_3s: int = 0


@dataclass(frozen=True, slots=True)
class Usual:
    """The middle day of the fortnight, one figure per step.

    Every figure is ``None`` where too few days spent to have a middle
    worth naming - see :data:`MIN_USUAL_DAYS`.
    """

    days: int = 0
    # What ``per`` results cost on the middle day: one, or a thousand
    # showings - see ``core.agent.benchmark.per_of``.
    cost_minor: int | None = None
    link_ctr_bp: int | None = None
    cpm_minor: int | None = None
    hook_bp: int | None = None


# Days that spent before a fortnight has a middle. Fewer is a week of
# somebody's first campaign, and its median is a single good or bad day.
MIN_USUAL_DAYS = 5


# How many finished days "the last days" are: the brief's trend reads three.
TREND_DAYS = 3

# The price trend's two bars, as a share of the usual price: a warning,
# then a reason to act. The brief's values, and the only "dearer" there is:
# every rule, card, message and report that calls a price dear calls it
# dear here - see :func:`price_level`.
TREND_WARN_PCT = 150
TREND_ACT_PCT = 200

# How far past its usual a price is: said on the morning's report, or acted on.
PriceLevel = Literal["warn", "act"]


def cost_trend(
    *, spend_minor: int, count: int | None, usual_cost_minor: int | None, per: int = 1
) -> int | None:
    """What the last days' result cost, as a percentage of the usual price.

    A stretch with spend and no result is priced as though one had come -
    the least it could have cost - so money going nowhere reads as the rise
    it is rather than as no trend at all. ``None`` where there is nothing
    to compare: no usual price, no spend, or a result nothing counts.
    """
    if count is None or not usual_cost_minor or spend_minor <= 0:
        return None
    return round(spend_minor * per * 100 / (max(count, 1) * usual_cost_minor))


def price_level(
    *,
    spend_minor: int,
    count: int | None,
    usual_cost_minor: int | None,
    window_spend_minor: int,
    per: int = 1,
) -> PriceLevel | None:
    """How far the last days' price is past the usual one, or ``None``.

    The brief's one reading of "dearer": the last three finished days
    against the fortnight's median day, past :data:`TREND_WARN_PCT` a
    warning and past :data:`TREND_ACT_PCT` a reason to act - and neither
    before the group spent three results' worth, see
    :mod:`core.agent.sufficiency`. ``window_spend_minor`` is that money:
    the whole window's, not the three days'. The brief asks whether the
    group has said enough, and a small budget's three days never reach
    three results' worth however dear they were.
    """
    if not enough_spent(
        spend_minor=window_spend_minor, usual_cost_minor=usual_cost_minor, per=per
    ):
        return None
    trend = cost_trend(
        spend_minor=spend_minor, count=count, usual_cost_minor=usual_cost_minor, per=per
    )
    if trend is None or trend <= TREND_WARN_PCT:
        return None
    return "act" if trend > TREND_ACT_PCT else "warn"


def usual_level(days: Sequence[DayFigures], *, per: int = 1) -> Usual:
    """The median day of these, over the days that spent.

    ``per`` is how many results one price is for - a thousand for showings.
    """
    spent = [day for day in days if day.spend_minor > 0]
    if len(spent) < MIN_USUAL_DAYS:
        return Usual(days=len(spent))
    return Usual(
        days=len(spent),
        cost_minor=_usual_cost(spent, per=per),
        link_ctr_bp=_middle(
            per_ten_thousand(part=day.link_clicks, whole=day.impressions)
            for day in spent
        ),
        cpm_minor=_middle(
            round(day.spend_minor * 1_000 / day.impressions)
            for day in spent
            if day.impressions > 0
        ),
        hook_bp=_middle(
            per_ten_thousand(part=day.video_views_3s, whole=day.video_impressions)
            for day in spent
        ),
    )


def _usual_cost(days: list[DayFigures], *, per: int) -> int | None:
    """The middle day's price, a day with no result being the dearest.

    Where the middle day brought nothing, the fortnight pooled instead -
    see the module docstring. ``None`` only where nothing at all came in.
    """
    priced = sorted(
        (
            round(day.spend_minor * per / day.results) if day.results > 0 else None
            for day in days
        ),
        key=lambda cost: (cost is None, cost or 0),
    )
    middle = priced[(len(priced) - 1) // 2]
    if middle is not None:
        return middle
    results = sum(day.results for day in days)
    if results <= 0:
        return None
    return round(sum(day.spend_minor for day in days) * per / results)


def _middle(values: Iterable[int | None]) -> int | None:
    """The lower median of the values that exist, or ``None``."""
    present = [value for value in values if value is not None]
    return int(median_low(present)) if present else None


__all__ = [
    "MIN_USUAL_DAYS",
    "TREND_ACT_PCT",
    "TREND_DAYS",
    "TREND_WARN_PCT",
    "DayFigures",
    "PriceLevel",
    "Usual",
    "cost_trend",
    "price_level",
    "usual_level",
]
