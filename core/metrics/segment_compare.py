"""Which slice of an audience is cheap, and which one is burning money.

The arithmetic behind "twenty-five to thirty-four year old women cost a
third of what everybody else did". One cut of one object over one range
goes in, a ranking comes out, and nothing in between touches a clock, a
database or a provider.

Five rules shape all of it.

**The basis is the provider's lead count, and it says so in every name.**
A lead in this product is a form somebody filled in, and it does not come
back with an age on it - our own lead table has no segment and cannot have
one. So a cost per lead per segment can only ever be built on what the
platform reported, which is a different number from the one the rest of
this product reasons about. The field is ``cpl_reported_minor`` for that
reason, and there is deliberately no cost per *qualified* lead here at all:
quality is a human verdict about a lead we hold, and we cannot say which
slice that lead came from.

**A cheap segment and a small segment look identical until you count.** One
lead at half the usual price is not a discovery, it is one lead; the count
of leads a verdict rests on has a relative error of roughly one over its
square root, so at four leads the cost per lead is worth about plus or minus
half of itself. Segments under the floor are kept and reported, never
ranked - dropping them silently would make a cut of twenty-one cells look
like a cut of three.

**A segment with spend and no leads is the most expensive one there is, and
a ranking by cost per lead cannot show it.** Its cost per lead is not
infinite, it is undefined - there is nothing to divide by. So those come
back in their own list, decided by a test that needs no currency and no
threshold anybody has to maintain: this slice was given enough money to have
produced the floor number of leads *at the rate this cut converts where it
converts at all*, and it did not.

**There are three ways to fail here, not two.** A slice that never had the
money is noise. One that had it and returned nothing at all is waste. Between
them sits one that had it and returned *some* leads - it converts, just
badly, and unlike waste it has a cost per lead. Calling all three the same
thing is how a placement earning eight leads gets switched off beside one
that earned none.

**How much is at stake rides on every slice.** ``spend_share`` is what turns
"this placement produced nothing" into a decision: at two percent of the
cut's money it is not worth an edit that restarts a learning phase, at forty
it is the whole problem. The threshold stays with the caller, as the floor
does.
"""

from dataclasses import dataclass
from typing import Final

from adskit import MinorUnits

from core.metrics.contracts import cost_per, share

# How many leads a segment needs before its cost per lead is ranked.
#
# Ten, and the number comes from the error rather than from taste. A count
# of events has a relative standard error of about one over its square root,
# so ten leads is a cost per lead worth roughly a third of itself either way,
# and the *ratio* of two such segments carries both errors - about forty-five
# percent. Which is the honest reading of this floor: at ten leads "three
# times cheaper" means something and "twenty percent cheaper" does not.
#
# Not raised further, because a floor high enough to make small differences
# trustworthy is a floor that answers nothing on a real account: a fortnight
# of one ad set spread over twenty-one age-and-gender cells does not give
# every cell twenty-five leads. So the count each verdict rests on is
# carried out with the verdict, and the caller decides what it needs.
MIN_SEGMENT_LEADS: Final = 10


@dataclass(frozen=True, slots=True)
class SegmentFigures:
    """One slice of one cut, already summed over the range.

    Counts only, and every one of them additive - which is what makes
    summing a range legitimate in the first place. ``reach`` is deliberately
    absent even though the table stores it: it counts people, so a range's
    reach is not the sum of its days. Which is also why no frequency can be
    computed here - see :func:`core.metrics.frequency`, which takes one row.
    """

    segment: str
    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    # The **provider's** count. See the module note: there is no other kind
    # available per segment, and there never will be.
    leads_reported: int = 0


@dataclass(frozen=True, slots=True)
class SegmentCost:
    """What one slice cost, and how that compares with the rest of the cut.

    ``cpl_index`` is the figure meant to be read: a hundred is the cut's own
    average, sixty is forty percent cheaper than it, and two hundred is
    twice as expensive. An index rather than a raw amount because it is the
    only form in which a rule can be written once - "twice the average" means
    the same thing in two currencies, on two accounts and in two months,
    where "over thirty thousand" means nothing outside one account.

    Both are ``None`` for a slice with no leads, and that is not a zero. Zero
    is a cost somebody reads as free, and a segment that spent money and
    produced nothing is the opposite of free.

    ``spend_share`` is the other half of every verdict: the list says whether
    a slice failed, this says whether the failure was worth anything. A whole
    percentage of the cut's own spend, so it reads the same in any currency -
    and it is what separates a placement quietly taking a third of the budget
    from one taking two percent when both produced nothing.
    """

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
    """A whole cut, sorted into what can be said about each slice.

    Four lists rather than one sorted one, because they answer different
    questions and mixing them produces the classic bad reading - a cell with
    one lead sitting at the top of a ranking labelled "cheapest".

    ``ranked``  - enough leads to compare. Cheapest first.
    ``barren``  - had the budget to produce leads at the rate the rest of
                  the cut manages, and produced **none**. Biggest spender
                  first, because that is the order the money was wasted in.
                  This is the list an exclusion is decided from.
    ``weak``    - had that same budget and produced *some* leads, fewer than
                  the floor. Not waste and not comparable: it converts, at a
                  price this says nothing reliable about. Biggest spender
                  first.
    ``thin``    - never had the money to say anything at all. Kept so the
                  cut adds up and a screen can show what it is not saying.

    Every slice handed in comes back in exactly one of them.

    ``average_cpl_minor`` is the whole cut's own cost per lead - total spend
    over total reported leads, across every slice including the ones in
    ``thin``. It is the index's base and is ``None`` when the cut produced no
    leads at all, which makes every verdict here ``None`` as well: there is
    nothing to be cheaper *than*.
    """

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
    """Sort one cut's slices by what can be said about each of them.

    The average is taken over **every** slice handed in, not over the ones
    that survive the floor. A base computed only from the segments that did
    well is a base every one of them beats.

    The order of the tests is the meaning of the lists. Comparable first;
    then whether the slice ever had enough money to be judged - everything
    that did not is noise. Only among those that did does it matter whether
    any leads came back.

    ``per`` is how many results the cost is the cost *of*: a thousand for
    the countable that costs less than a currency's smallest unit. It
    multiplies the two costs and nothing else - the index is their ratio.
    """
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
    """The cut's own cost per lead, or nothing when it produced none.

    Every slice's spend over every slice's leads, the slices that produced
    nothing included: what the advertiser actually paid per lead here, and
    the base the index is read against.

    Nothing is also the answer when the cut produced leads against no
    spend. It is the base every index below is divided by, so a nought
    here would take the whole comparison down with it.
    """
    return cost_per(
        MinorUnits(sum(row.spend_minor for row in rows) * per),
        sum(row.leads_reported for row in rows),
    )


def _earning_rate(rows: list[SegmentFigures]) -> MinorUnits | None:
    """What a lead costs in the slices that produced any.

    A second average, and not the one above, because only this one can be
    used as a bar. Waste sits in the numerator of :func:`_average_cpl`, so a
    cut with a lot of barren spend has a high average - and a bar built on it
    would rise exactly as fast as the thing it is meant to catch. On a cut
    with twenty leads, a slice would have to outspend every other slice
    combined before it could be called wasteful at all.

    Here the barren slices are left out of both halves, which makes this "the
    rate this cut converts at, where it converts". Money handed to a slice
    that beat that rate ``need`` times over and produced nothing is money
    that had its chance.
    """
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
    """Whether this slice was given enough money to have produced leads.

    The test that makes "expensive" sayable about a segment with no cost per
    lead. Enough money means what ``need`` leads cost in the slices that
    produced any - so it scales with the account, the currency and the
    month, and there is no threshold for anybody to keep up to date.

    It decides *whether* a slice can be judged, not what the verdict is: one
    that fails it is noise, and one that passes is barren or weak according
    to whether anything came back at all.

    ``False`` when nothing anywhere produced a lead. A cut with no rate has
    no bar, and calling every slice wasteful because the whole ad set was is
    a verdict about the ad set, which this function is not the place for.
    """
    if rate is None:
        return False
    return cost.spend_minor >= rate * need


def _by_cost(cost: SegmentCost) -> tuple[int, str]:
    """Cheapest first. The segment name breaks ties so the order is stable."""
    return (cost.cpl_reported_minor or 0, cost.segment)


def _by_spend(cost: SegmentCost) -> tuple[int, str]:
    """Biggest spender first - the order the money went out in."""
    return (-cost.spend_minor, cost.segment)
