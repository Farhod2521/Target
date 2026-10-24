"""The figures a dashboard is built from, before anything formats them.

Money is an integer count of minor units and a currency code, like
everywhere else. Counts are counts. Nothing here is a string, because a
string is a decision about a reader and this package has none.

The distinction that runs through the whole file: **sums are additive and
rates are not**. Spend, impressions, clicks and leads can be added across
days and across ad sets. A cost per lead cannot - a period's CPL is its
total spend over its total leads, never the mean of its days - and neither
can reach, which counts people and would double-count anybody an account
showed two different ad sets to.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from adskit import MinorUnits

# Which way a figure moved, and nothing about whether that is good news.
# Falling costs and falling leads are both "down", and only the caller knows
# which one it is looking at.
Direction = Literal["up", "down", "flat"]


@dataclass(frozen=True, slots=True)
class DayFigures:
    """One day, with everything already summed across the objects in it.

    ``leads`` is ours and ``leads_reported`` is the provider's, and they are
    kept apart on purpose. Ours is the one a person can act on - it has a
    name and a phone number behind it - and the provider's is the one that
    proves a webhook went missing when the two disagree.

    ``qualified`` is a subset of ``leads``: the ones somebody looked at and
    said were worth the money. It is the only number here the provider
    cannot know, and the whole reason this product computes a cost the
    provider cannot.
    """

    day: date
    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    # The clicks that went where the money was being spent to send them.
    #
    # Kept beside ``clicks`` rather than instead of it, because they answer
    # different questions and the funnel needs this one. ``clicks`` counts
    # every tap on the unit - expanding a caption, opening the page's
    # profile, tapping a video - so a creative that is interesting to look
    # at wins on it and sends nobody anywhere.
    link_clicks: int = 0
    leads: int = 0
    qualified: int = 0
    leads_reported: int = 0
    # The provider's own count of a result that is not a lead, and the
    # estimate of who would remember an advert bought to be remembered.
    #
    # **Exactly one of these and the lead count is filled on any given
    # row**, decided by what the ad set optimises for - so they are never
    # added together and never added to ``leads``. A conversation has no
    # name, no telephone number and no verdict, and the cost per qualified
    # lead divides by exactly those.
    #
    # Named the way ``apps.metrics.selectors.facts.CampaignSums`` names
    # them, on purpose: the screen decides which figure a kind of campaign
    # is judged on and then reads that one attribute off whichever of the
    # two shapes it has in hand. Two spellings would be two mappings.
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0


@dataclass(frozen=True, slots=True)
class Totals:
    """A whole range, summed. The same fields without the day.

    Deliberately not a ``DayFigures`` with a meaningless date. A range that
    can be passed where a day is expected is a range that eventually gets
    plotted as one.
    """

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
        """What one lead cost, or nothing when there were none.

        ``None`` rather than zero. Zero is a cost somebody could read as
        "free", and a range with spend and no leads is the opposite of
        free - it is the most expensive state a campaign can be in.
        """
        return cost_per(self.spend_minor, self.leads)

    @property
    def cpql_minor(self) -> MinorUnits | None:
        """What one *usable* lead cost. The figure this product exists for.

        No ad platform can compute this: it needs a human verdict that only
        the advertiser has. The gap between it and :attr:`cpl_minor` is the
        product's entire claim.
        """
        return cost_per(self.spend_minor, self.qualified)

    @property
    def reported_cpl_minor(self) -> MinorUnits | None:
        """What the **provider** says one lead cost, or nothing.

        Spend over ``leads_reported`` rather than over ``leads``, and it
        exists for one situation: a cabinet connected to an ad account that
        has been running for years. The ninety days of history fetched on
        the first sync carry the provider's own lead count for every
        campaign in them, and none of those leads ever reached this product
        - they were collected before there was anything here to collect
        them. So :attr:`cpl_minor` is nothing and :attr:`cpql_minor` is
        nothing, and the account is not empty at all.

        **Never mixed with the other two.** It is a different number from a
        different source and it can disagree with ours - a webhook that was
        lost, a test submission, a lead either side of midnight. Whoever
        shows it has to say whose count it is.
        """
        return cost_per(self.spend_minor, self.leads_reported)

    @property
    def quality_share(self) -> int:
        """What percentage of leads were worth having, rounded.

        Over ``leads`` and not over the ones somebody has got round to
        marking. A share computed only over marked leads climbs every time
        the owner marks a good one and stalls when they stop looking, which
        makes it a measure of their attention rather than of the campaign.
        """
        return share(part=self.qualified, whole=self.leads)


@dataclass(frozen=True, slots=True)
class Movement:
    """How a figure compares with the range before it.

    ``is_good`` is separate from ``direction`` because the two disagree half
    the time: a cost going down is good news and a lead count going down is
    not, and a screen that colours every arrow the same way teaches people
    to ignore it.
    """

    percent: int = 0
    direction: Direction = "flat"
    is_good: bool = False


def cost_per(spend_minor: MinorUnits, count: int) -> MinorUnits | None:
    """Cost per one of something, or nothing when the division says nothing.

    **The only place this division is written.** Spread over several call
    sites, some would carry both refusals below and some only one, and the
    difference would not be visibly wrong: a screen that tests the result
    for truth before printing it treats nought as false. A guard that holds
    by luck downstream is a guard that stops holding the day somebody
    prints the figure without the test.

    Two refusals.

    **No count**: dividing by nought has no answer, and a range with spend
    and no leads is the most expensive state a campaign can be in rather
    than a free one.

    **No spend**: the arithmetic works and the answer is a lie. Leads
    arrive continuously and figures are collected once a night, so an
    account looked at before its first sync of the day has today's leads
    against nothing spent - and it would be told each one cost nothing.
    That is the same reading a cabinet gets when its leads come from
    somewhere its spend does not, which is the failure this pair of guards
    exists to make impossible to show.

    Nought is never the honest answer here. Where it is arithmetically
    true - leads that arrived with no advertising behind them - a *cost*
    per lead is not the figure being asked for anyway.
    """
    if count <= 0 or spend_minor <= 0:
        return None
    return MinorUnits(round(spend_minor / count))


def share(*, part: int, whole: int) -> int:
    """``part`` as a whole percentage of ``whole``. Zero divides to zero."""
    if whole <= 0:
        return 0
    return round(part / whole * 100)
