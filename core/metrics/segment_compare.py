"""Which slice of an audience is cheap, and which one is burning money."""

from dataclasses import dataclass
from typing import Final

from adskit import MinorUnits

from core.metrics.contracts import cost_per, share

MIN_SEGMENT_LEADS: Final = 10


@dataclass(frozen=True, slots=True)
class SegmentFigures:
    """One slice of one cut, already summed over the range."""

    segment: str
    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    leads_reported: int = 0


@dataclass(frozen=True, slots=True)
class SegmentCost:
    """What one slice cost, and how that compares with the rest of the cut."""

    segment: str
    spend_minor: MinorUnits
    impressions: int
    clicks: int
    leads_reported: int
    cpl_reported_minor: MinorUnits | None = None
    cpl_index: int | None = None
    spend_share: int = 0


@dataclass(frozen=True, slots=True)
class SegmentComparison:
    """A whole cut, sorted into what can be said about each slice."""

    ranked: tuple[SegmentCost, ...] = ()
    barren: tuple[SegmentCost, ...] = ()
    weak: tuple[SegmentCost, ...] = ()
    thin: tuple[SegmentCost, ...] = ()
    average_cpl_minor: MinorUnits | None = None
    min_leads: int = MIN_SEGMENT_LEADS

    @property
    def cheapest(self) -> SegmentCost | None:
        """The best comparable slice, or nothing when none could be compared."""
        return self.ranked[0] if self.ranked else None

    @property
    def dearest(self) -> SegmentCost | None:
        """The worst comparable slice. Not the worst slice - see ``barren``."""
        return self.ranked[-1] if self.ranked else None


def compare_segments(
    rows: list[SegmentFigures], *, min_leads: int = MIN_SEGMENT_LEADS, per: int = 1
) -> SegmentComparison:
    """Sort one cut's slices by what can be said about each of them."""
    average = _average_cpl(rows, per=per)
    earning = _earning_rate(rows)
    spent = sum(row.spend_minor for row in rows)
    costs = [_cost(row, average=average, spent=spent, per=per) for row in rows]

    ranked: list[SegmentCost] = []
    barren: list[SegmentCost] = []
    weak: list[SegmentCost] = []
    thin: list[SegmentCost] = []
    for cost in costs:
        if cost.leads_reported >= min_leads:
            ranked.append(cost)
        elif not _had_its_chance(cost, rate=earning, need=min_leads):
            thin.append(cost)
        elif cost.leads_reported == 0:
            barren.append(cost)
        else:
            weak.append(cost)

    return SegmentComparison(
        ranked=tuple(sorted(ranked, key=_by_cost)),
        barren=tuple(sorted(barren, key=_by_spend)),
        weak=tuple(sorted(weak, key=_by_spend)),
        thin=tuple(sorted(thin, key=_by_spend)),
        average_cpl_minor=average,
        min_leads=min_leads,
    )


def _average_cpl(rows: list[SegmentFigures], *, per: int = 1) -> MinorUnits | None:
    """The cut's own cost per lead, or nothing when it produced none."""
    return cost_per(
        MinorUnits(sum(row.spend_minor for row in rows) * per),
        sum(row.leads_reported for row in rows),
    )


def _earning_rate(rows: list[SegmentFigures]) -> MinorUnits | None:
    """What a lead costs in the slices that produced any."""
    earning = [row for row in rows if row.leads_reported > 0]
    return cost_per(
        MinorUnits(sum(row.spend_minor for row in earning)),
        sum(row.leads_reported for row in earning),
    )


def _cost(
    row: SegmentFigures, *, average: MinorUnits | None, spent: int, per: int = 1
) -> SegmentCost:
    """One slice's own cost, and where it sits against the cut's average."""
    cpl = cost_per(MinorUnits(row.spend_minor * per), row.leads_reported)
    return SegmentCost(
        segment=row.segment,
        spend_minor=row.spend_minor,
        impressions=row.impressions,
        clicks=row.clicks,
        leads_reported=row.leads_reported,
        cpl_reported_minor=cpl,
        cpl_index=(round(cpl / average * 100) if cpl is not None and average else None),
        spend_share=share(part=row.spend_minor, whole=spent),
    )


def _had_its_chance(cost: SegmentCost, *, rate: MinorUnits | None, need: int) -> bool:
    """Whether this slice was given enough money to have produced leads."""
    if rate is None:
        return False
    return cost.spend_minor >= rate * need


def _by_cost(cost: SegmentCost) -> tuple[int, str]:
    """Cheapest first. The segment name breaks ties so the order is stable."""
    return (cost.cpl_reported_minor or 0, cost.segment)


def _by_spend(cost: SegmentCost) -> tuple[int, str]:
    """Biggest spender first - the order the money went out in."""
    return (-cost.spend_minor, cost.segment)
