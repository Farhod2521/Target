"""Turning days into the four things a dashboard says."""

from collections.abc import Iterable, Sequence

from adskit import MinorUnits

from core.metrics.contracts import (
    DayFigures,
    Direction,
    Movement,
    Totals,
    cost_per,
    share,
)


def total(days: Iterable[DayFigures]) -> Totals:
    """Every additive figure summed. Rates are properties of the result."""
    rows = list(days)
    return Totals(
        spend_minor=MinorUnits(sum(row.spend_minor for row in rows)),
        impressions=sum(row.impressions for row in rows),
        clicks=sum(row.clicks for row in rows),
        link_clicks=sum(row.link_clicks for row in rows),
        leads=sum(row.leads for row in rows),
        qualified=sum(row.qualified for row in rows),
        leads_reported=sum(row.leads_reported for row in rows),
        results=sum(row.results for row in rows),
        recallers=sum(row.recallers for row in rows),
        profile_visits=sum(row.profile_visits for row in rows),
    )


def movement(
    *, now: float | None, before: float | None, lower_is_better: bool
) -> Movement:
    """How one figure compares with the same figure a period earlier."""
    if now is None or before is None or not before:
        return Movement()

    change = (now - before) / before * 100
    percent = round(abs(change))
    if percent == 0:
        return Movement()

    direction: Direction = "up" if change > 0 else "down"
    return Movement(
        percent=percent,
        direction=direction,
        is_good=(direction == "down") if lower_is_better else (direction == "up"),
    )


LEAD_RUNGS: tuple[tuple[str, str], ...] = (
    ("shown", "impressions"),
    ("clicked", "link_clicks"),
    ("submitted", "leads"),
)


def funnel(
    totals: Totals, *, rungs: Sequence[tuple[str, str]] = LEAD_RUNGS
) -> tuple[tuple[str, int, int | None], ...]:
    """Each rung as ``(name, value, share of the rung above)``."""
    steps = tuple((name, int(getattr(totals, field))) for name, field in rungs)
    return tuple(
        (name, value, _step_share(steps, index))
        for index, (name, value) in enumerate(steps)
    )


def _step_share(steps: tuple[tuple[str, int], ...], index: int) -> int | None:
    """One step against the one above it, or nothing where there is none."""
    if index == 0:
        return None
    above = steps[index - 1][1]
    return share(part=steps[index][1], whole=above) if above else None


def daily_rate(
    days: Sequence[DayFigures], *, field: str = "leads", per: int = 1
) -> list[int | None]:
    """One cost per day, for plotting. ``None`` where the day had none."""
    return [
        cost_per(MinorUnits(row.spend_minor * per), int(getattr(row, field)))
        for row in days
    ]
