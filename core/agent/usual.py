"""What a pair's advertising usually does: the median of its last fortnight."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median_low

from core.agent.funnel import per_ten_thousand


@dataclass(frozen=True, slots=True)
class DayFigures:
    """One day of one family of groups, summed across them."""

    spend_minor: int = 0
    impressions: int = 0
    link_clicks: int = 0
    results: int = 0
    video_impressions: int = 0
    video_views_3s: int = 0
    frequency: int = 0


@dataclass(frozen=True, slots=True)
class Usual:
    """The middle day of the fortnight, one figure per step."""

    days: int = 0
    cost_minor: int | None = None
    link_ctr_bp: int | None = None
    cpm_minor: int | None = None
    frequency: int | None = None
    hook_bp: int | None = None


MIN_USUAL_DAYS = 5


TREND_WARN_PCT = 150
TREND_ACT_PCT = 200


def cost_trend(
    *, spend_minor: int, count: int | None, usual_cost_minor: int | None, per: int = 1
) -> int | None:
    """What the last days' result cost, as a percentage of the usual price."""
    if count is None or not usual_cost_minor or spend_minor <= 0:
        return None
    return round(spend_minor * per * 100 / (max(count, 1) * usual_cost_minor))


def usual_level(days: Sequence[DayFigures], *, per: int = 1) -> Usual:
    """The median day of these, over the days that spent."""
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
        frequency=_middle(day.frequency for day in spent if day.frequency > 0),
        hook_bp=_middle(
            per_ten_thousand(part=day.video_views_3s, whole=day.video_impressions)
            for day in spent
        ),
    )


def _usual_cost(days: list[DayFigures], *, per: int) -> int | None:
    """The middle day's price, a day with no result being the dearest."""
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
    "TREND_WARN_PCT",
    "DayFigures",
    "Usual",
    "cost_trend",
    "usual_level",
]
