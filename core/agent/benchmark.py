"""What an account's comparable groups do at every step, summed.

The only reference a diagnosis compares a group with. The provider
publishes no good click-through rate or cost per thousand, and a
barbershop's and a clinic's differ by an order of magnitude - so the honest
bar is the same owner's other groups.

**Comparable means bought for the same result.** A group is judged on what
one of its results costs - a lead, a conversation, a call, a visit, a
thousand showings - against the account's other groups bought for that
result. Every other figure here explains a price; none of them is a
verdict on its own. A conversation group whose conversations are cheap is
working, however few people clicked it.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from adskit import MinorUnits

from core.agent.contracts import Policy
from core.agent.facts import AdSetFacts
from core.agent.funnel import Funnel, per_ten_thousand
from core.metrics import Outcome, Totals, cost_per

# How many results one price is quoted over. A single showing costs a
# fraction of the smallest unit of money and would round to nought, so a
# showing is priced by the thousand - the figure the screens print too.
PER: Final[Mapping[str, int]] = {"view": 1_000}


def per_of(family: str) -> int:
    """How many results one price here is for."""
    return PER.get(family, 1)


def family_of(item: AdSetFacts) -> Outcome:
    """The result this group was bought for, which is who it is compared with.

    ``counts_leads`` first: it is the field every lead rule already trusts,
    and a group it calls a lead group is one whatever else was recorded.
    """
    return "lead" if item.counts_leads else item.outcome


def count_in(*, totals: Totals, link_clicks: int, family: str) -> int | None:
    """How many results of this kind the figures hold, or ``None``.

    ``None`` is a kind nothing here counts - a purchase on somebody else's
    website, a goal nobody wrote down - and it is not nought: nought is a
    result, and this is the absence of a way to have one.

    A lead is counted the larger way, for the reason :func:`lead_count`
    gives. A visit to the site is Ads Manager's own result for the group -
    a link click or a landing page view, whichever it was bought for.
    """
    if family == "lead":
        return max(totals.leads, totals.leads_reported)
    if family in ("chat", "call"):
        return totals.results
    if family == "click":
        return totals.results
    if family == "view":
        return totals.impressions
    if family == "recall":
        return totals.recallers
    if family == "profile":
        return totals.profile_visits
    return None


def result_count(item: AdSetFacts) -> int | None:
    """How many of the results it was bought for this group brought in."""
    return count_in(
        totals=item.totals, link_clicks=item.funnel.link_clicks, family=family_of(item)
    )


def result_cost(*, spend_minor: int, count: int | None, family: str) -> int | None:
    """What one result cost - a thousand, for showings - or nothing.

    Nothing for no result at all: a price of nought would call the most
    expensive state a campaign can be in free.
    """
    if not count or count <= 0:
        return None
    return round(spend_minor * per_of(family) / count)


@dataclass(frozen=True, slots=True)
class Benchmark:
    """The funnel summed over one family of groups.

    A family is one kind of result: a group bought for clicks has a
    click-through rate a lead group never reaches, and one sum over both
    would call every lead group weak.
    """

    funnel: Funnel = field(default_factory=Funnel)
    # The same two counts over the groups that ran a video. An image cannot
    # hold anyone for three seconds, so it has no place in the average.
    video_impressions: int = 0
    video_views_3s: int = 0
    leads: int = 0
    family: str = "lead"
    # The family's own results, counted the way ``count_in`` counts them -
    # except leads, which are counted over the family as a whole; see
    # :func:`benchmark`.
    results: int = 0

    @property
    def hook_bp(self) -> int | None:
        return per_ten_thousand(part=self.video_views_3s, whole=self.video_impressions)

    @property
    def click_to_lead_bp(self) -> int | None:
        return per_ten_thousand(part=self.leads, whole=self.funnel.link_clicks)

    @property
    def cpl_minor(self) -> int | None:
        if self.leads <= 0 or self.funnel.spend_minor <= 0:
            return None
        return round(self.funnel.spend_minor / self.leads)

    @property
    def cost_minor(self) -> int | None:
        """What one of the family's results usually costs on this account."""
        if self.funnel.spend_minor <= 0:
            return None
        return result_cost(
            spend_minor=self.funnel.spend_minor, count=self.results, family=self.family
        )


def lead_count(item: AdSetFacts) -> int:
    """The larger of our lead count and the provider's.

    Either can be short - a lost webhook on ours, a lead either side of
    midnight on theirs - and a diagnosis that read the shorter one would
    report a working form as a stalled one.
    """
    return max(item.totals.leads, item.totals.leads_reported)


def lead_cost(totals: Totals) -> MinorUnits | None:
    """What one lead cost over these totals, counted the way ``lead_count`` is.

    The larger of the two counts, for the same reason: a lost webhook on our
    side or a lead either side of midnight on the provider's would make a
    working group look dearer than it is - and a dearer look is what takes
    money away from it.
    """
    return cost_per(totals.spend_minor, max(totals.leads, totals.leads_reported))


def benchmark(adsets: Iterable[AdSetFacts], *, family: str = "lead") -> Benchmark:
    """The groups handed in, summed. Groups nobody was shown are left out.

    **Leads are counted the way the rules count them**: the larger of the
    two sums, ours or the provider's - :func:`lead_cost` over the account's
    lead totals. It is the price the rules measure against, the card's
    "odatda" and the model's account lines, and it has to be one figure: a
    sum of each group's larger count is a different number whenever the two
    counts disagree in opposite directions on two groups, and "odatda
    50 000" above a card saying 35 000 leaves the owner unsure which to
    trust.
    """
    shown = [item for item in adsets if item.funnel.impressions > 0]
    videos = [item for item in shown if item.funnel.video_plays > 0]
    leads = max(
        sum(item.totals.leads for item in shown),
        sum(item.totals.leads_reported for item in shown),
    )
    return Benchmark(
        funnel=Funnel(
            spend_minor=sum(item.funnel.spend_minor for item in shown),
            impressions=sum(item.funnel.impressions for item in shown),
            link_clicks=sum(item.funnel.link_clicks for item in shown),
            landing_page_views=sum(item.funnel.landing_page_views for item in shown),
            video_plays=sum(item.funnel.video_plays for item in shown),
            video_views_3s=sum(item.funnel.video_views_3s for item in shown),
        ),
        video_impressions=sum(item.funnel.impressions for item in videos),
        video_views_3s=sum(item.funnel.video_views_3s for item in videos),
        leads=leads,
        family=family,
        results=(
            leads
            if family == "lead"
            else sum(result_count(item) or 0 for item in shown)
        ),
    )


def benchmarks(adsets: Iterable[AdSetFacts]) -> dict[str, Benchmark]:
    """``{family: its benchmark}`` - every group compared only with its own kind."""
    families: dict[str, list[AdSetFacts]] = {}
    for item in adsets:
        families.setdefault(family_of(item), []).append(item)
    return {
        family: benchmark(members, family=family)
        for family, members in families.items()
    }


def peers(adsets: Iterable[AdSetFacts], item: AdSetFacts) -> Benchmark:
    """The benchmark of this group's kind, without this group in it.

    A group compared with a sum it is part of is partly compared with
    itself: on an account with one group it is wholly so, and "dearer than
    your other adverts" is said about adverts that do not exist.
    """
    family = family_of(item)
    return benchmark(
        (other for other in adsets if other is not item and family_of(other) == family),
        family=family,
    )


def peers_lead_cost(totals: Totals, item: AdSetFacts) -> MinorUnits | None:
    """:func:`lead_cost` over the account's lead totals, this group taken out."""
    spend = max(0, totals.spend_minor - item.totals.spend_minor)
    leads = max(
        totals.leads - item.totals.leads,
        totals.leads_reported - item.totals.leads_reported,
        0,
    )
    return cost_per(MinorUnits(spend), leads)


def results_are_poor(*, item: AdSetFacts, bench: Benchmark, policy: Policy) -> bool:
    """Whether what this group's results cost is too much to leave alone.

    Against the account's groups bought for the same result, at
    ``Policy.lose_share_pct`` - the share the budget rules call dear. No
    result at all is poor once the group has spent what one normally costs
    here; on an account with none anywhere, once it has spent anything.

    **Never for a group whose result nothing counts.** A purchase on
    somebody else's website has no price here, and judging it by its
    clicks instead is exactly the mistake this function exists to stop.
    """
    count = result_count(item)
    if count is None:
        return False
    spend = item.totals.spend_minor
    per = per_of(family_of(item))
    usual = bench.cost_minor
    if usual is None:
        return count == 0 and spend > 0
    if count == 0:
        return spend * per >= usual
    return spend * per * 100 >= usual * count * policy.lose_share_pct


__all__ = [
    "PER",
    "Benchmark",
    "benchmark",
    "benchmarks",
    "count_in",
    "family_of",
    "lead_cost",
    "lead_count",
    "peers",
    "peers_lead_cost",
    "per_of",
    "result_cost",
    "result_count",
    "results_are_poor",
]
