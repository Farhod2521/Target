"""One campaign's days, summed into every figure its panel can show.

``core.metrics.derive`` already sums a range into :class:`Totals`, and that
shape is deliberately narrow - six additive counts and the two costs the
dashboard turns on. The panel needs more: link clicks, video, and the three
counts that measure *people*.

So this is a second, wider pair rather than fields added to the first. The
reason is the rule ``Totals`` is built on. Everything in it may be added
across days; ``reach`` and the ``unique_`` counts may not, and a shape that
carried both kinds side by side is one where somebody eventually sums the
wrong half. Here the two are kept apart by construction: :class:`PanelDay`
holds a day, :func:`panel_total` sums only what may be summed, and the
people-counting figures are reached through :func:`newest_measured`, which
returns one day and says which.

Rates are recomputed from the sums and never averaged, the same rule as
next door: thirty days of CTR averaged together weights the day the ad was
shown twelve times the same as the day it was shown ten thousand.

No clock, no database, no formatting.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Final

from adskit import MinorUnits

from core.metrics.contracts import cost_per, share

# How many impressions a CPM is quoted per. Named rather than written into
# the division, so the figure and the word "ming" beside it on the screen
# cannot drift apart.
PER_MILLE: Final = 1000

# The scale the two fine-grained rates are returned in.
#
# **Hundredths of a percent, not percent.** A click-through rate is
# routinely below one percent, and :func:`core.metrics.share` rounds to a
# whole one - so every honest CTR this product could report would print as
# "0%". Ten thousand keeps two decimals without a float anywhere near the
# arithmetic: ``220`` is 2.20 percent, and the screen is what puts the
# comma in.
BASIS_POINTS: Final = 10_000


@dataclass(frozen=True, slots=True)
class PanelDay:
    """One campaign's day, in every count the panel may draw.

    Zeros rather than ``None`` throughout. An image campaign genuinely had
    no video plays and a paused day genuinely had no impressions; both are
    counts of nothing rather than questions nobody answered.

    The last three count **people** and are the reason this class exists as
    a day rather than as a range. See the module note.
    """

    day: date
    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    leads: int = 0
    qualified: int = 0
    leads_reported: int = 0
    # The leads that reached this product's own table. Equal to ``leads``
    # until a form campaign's screen puts the provider's count in that slot
    # - see :func:`with_provider_leads` - and then the "tushdi" beside it.
    received: int = 0
    # The provider's own count of a result that is not a lead, and the
    # estimate of who would remember an advert bought to be remembered.
    # Named as ``DayFigures`` names them, so one field name reads either
    # shape - see the note there.
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0
    video_plays: int = 0
    video_thruplays: int = 0
    reach: int = 0
    unique_clicks: int = 0

    @property
    def is_measured(self) -> bool:
        """Whether the provider had anything to say about this day.

        Impressions and not spend: a campaign delivering on credit, or one
        whose spend has not been reconciled yet, still reached somebody -
        and a day with reach is a day whose people-counting figures are
        real. A day with neither is a day the campaign was off.
        """
        return self.impressions > 0


@dataclass(frozen=True, slots=True)
class PanelTotals:
    """A range, with only the counts that may be added across days.

    ``unique_clicks`` is **deliberately absent**, and ``reach`` is never
    summed. Adding either up counts anybody who came back on a second day
    twice, and every ratio built on that sum is wrong in the direction that
    flatters. ``reach`` is the provider's own count for the whole range
    where one is stored and nought where none is; :func:`panel_total` never
    fills it.
    """

    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    leads: int = 0
    qualified: int = 0
    leads_reported: int = 0
    received: int = 0
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0
    video_plays: int = 0
    video_thruplays: int = 0
    reach: int = 0

    @property
    def cpl_minor(self) -> MinorUnits | None:
        """What one lead cost. ``None`` where the division says nothing."""
        return cost_per(self.spend_minor, self.leads)

    @property
    def cpql_minor(self) -> MinorUnits | None:
        """What one lead worth having cost. The figure the product is for."""
        return cost_per(self.spend_minor, self.qualified)

    @property
    def cpm_minor(self) -> MinorUnits | None:
        """What a thousand showings cost.

        The provider stores its own copy per day and it is not used here:
        a range's CPM is its spend over its impressions, and the mean of
        thirty daily CPMs is a different number that happens to look like
        one.
        """
        return cost_per(MinorUnits(self.spend_minor * PER_MILLE), self.impressions)

    @property
    def cpc_minor(self) -> MinorUnits | None:
        """What one click cost, counting every click on the unit."""
        return cost_per(self.spend_minor, self.clicks)

    @property
    def ctr_bp(self) -> int:
        """Clicks per ten thousand impressions. See :data:`BASIS_POINTS`."""
        return rate_bp(part=self.clicks, whole=self.impressions)

    @property
    def link_ctr_bp(self) -> int:
        """The same, for the clicks that went where the money was sent.

        The honest one. ``clicks`` counts expanding a caption and opening
        the page's profile, so a campaign can look busy on the headline
        rate while sending nobody anywhere.
        """
        return rate_bp(part=self.link_clicks, whole=self.impressions)

    @property
    def platform_cpl_minor(self) -> MinorUnits | None:
        """What the **provider** says one lead cost.

        Spend over the provider's own count rather than over ours, and the
        gap between the two is the point: a webhook that went missing shows
        up here as a cost that is lower than the one beside it, because the
        provider counted a lead this product never received.

        Computed rather than read back from the provider's own per-day
        figure, which is stored. A range's cost per lead is its spend over
        its leads and never the mean of its days.
        """
        return cost_per(self.spend_minor, self.leads_reported)

    @property
    def quality_share(self) -> int:
        """What percentage of the leads were worth having.

        Over every lead and not over the ones somebody got round to
        judging: a share computed only over judged leads rises whenever the
        owner marks a good one and stalls when they stop looking, which
        measures their attention rather than the campaign.
        """
        return share(part=self.qualified, whole=self.leads)

    @property
    def hold_share(self) -> int:
        """What share of the people who started the video stayed to the end.

        "The end" is the provider's own threshold - watched through, or
        fifteen seconds, whichever comes first.
        """
        return share(part=self.video_thruplays, whole=self.video_plays)


def with_provider_leads[T: (PanelDay, PanelTotals)](figures: T) -> T:
    """A form campaign's figures with the provider's lead count in the slot.

    What Ads Manager prints is what somebody compares this screen against,
    and two counts that differ for reasons nobody can act on - a webhook a
    minute late, a lead the page collected before it was connected - read as
    one of the two being broken. So the slot holds the provider's count and
    the price is divided by it, the same price Ads Manager prints; ours is
    kept in ``received``, which is what the screen says beside it when the
    two differ - a lead the provider counted and nobody here can call.

    Only where the provider has figures: a day it has not been read for yet
    keeps ours, which is the only count there is.
    """
    if not (figures.impressions or figures.spend_minor or figures.leads_reported):
        return replace(figures, received=figures.leads)
    return replace(figures, leads=figures.leads_reported, received=figures.leads)


def panel_total(days: Iterable[PanelDay]) -> PanelTotals:
    """Every additive figure summed. Rates are properties of the result."""
    rows = list(days)
    return PanelTotals(
        spend_minor=MinorUnits(sum(row.spend_minor for row in rows)),
        impressions=sum(row.impressions for row in rows),
        clicks=sum(row.clicks for row in rows),
        link_clicks=sum(row.link_clicks for row in rows),
        leads=sum(row.leads for row in rows),
        qualified=sum(row.qualified for row in rows),
        leads_reported=sum(row.leads_reported for row in rows),
        received=sum(row.received for row in rows),
        results=sum(row.results for row in rows),
        recallers=sum(row.recallers for row in rows),
        profile_visits=sum(row.profile_visits for row in rows),
        video_plays=sum(row.video_plays for row in rows),
        video_thruplays=sum(row.video_thruplays for row in rows),
    )


def newest_measured(days: Sequence[PanelDay]) -> PanelDay | None:
    """The most recent day the campaign actually ran, or nothing.

    Where the three people-counting figures come from. The *newest* rather
    than the whole range, because it is the only day whose reach the panel
    can state without inventing one - and the most recent is the one a
    question about wear-out is about.

    Skips the tail of days a paused campaign leaves behind. Reporting a
    reach of nothing because the campaign was off yesterday would read as
    an audience that vanished.
    """
    for row in reversed(days):
        if row.is_measured:
            return row
    return None


def frequency_bp(day: PanelDay | PanelTotals) -> int:
    """How often the average person reached saw the ad, in hundredths.

    ``240`` is two and a bit showings each. Not a share of anything - it
    passes a hundred as soon as somebody sees the ad twice, which is normal
    and is the point of the figure.

    Computed rather than read back from the provider, which is the rule the
    whole insights request is built on: counts are asked for and ratios are
    not, because a second copy of a division is a second answer that can
    disagree with ours.
    """
    return share(part=day.impressions, whole=day.reach)


def rate_bp(*, part: int, whole: int) -> int:
    """``part`` per ten thousand of ``whole``, rounded. Nought over nought.

    The finer-grained twin of :func:`core.metrics.share`, and it exists for
    one figure: a click-through rate rounded to whole percent is nought on
    almost every campaign this product runs.
    """
    if whole <= 0:
        return 0
    return round(part * BASIS_POINTS / whole)


__all__ = [
    "BASIS_POINTS",
    "PER_MILLE",
    "PanelDay",
    "PanelTotals",
    "frequency_bp",
    "newest_measured",
    "panel_total",
    "rate_bp",
    "with_provider_leads",
]
