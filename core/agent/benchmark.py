"""What an account's comparable groups do at every step, summed."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from adskit import MinorUnits

from core.agent.contracts import Policy
from core.agent.facts import AdSetFacts
from core.agent.funnel import Funnel, per_ten_thousand
from core.metrics import Outcome, Totals, cost_per

PER: Final[Mapping[str, int]] = {"view": 1_000}


def per_of(family: str) -> int:
    """How many results one price here is for."""
    return PER.get(family, 1)


def family_of(item: AdSetFacts) -> Outcome:
    """The result this group was bought for, which is who it is compared with."""
    return "lead" if item.counts_leads else item.outcome


def count_in(*, totals: Totals, link_clicks: int, family: str) -> int | None:
    """How many results of this kind the figures hold, or ``None``."""
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
    """What one result cost - a thousand, for showings - or nothing."""
    if not count or count <= 0:
        return None
    return round(spend_minor * per_of(family) / count)


@dataclass(frozen=True, slots=True)
class Benchmark:
    """The funnel summed over one family of groups."""

    funnel: Funnel = field(default_factory=Funnel)
    video_impressions: int = 0
    video_views_3s: int = 0
    leads: int = 0
    family: str = "lead"
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
    """The larger of our lead count and the provider's."""
    return max(item.totals.leads, item.totals.leads_reported)


def lead_cost(totals: Totals) -> MinorUnits | None:
    """What one lead cost over these totals, counted the way ``lead_count`` is."""
    return cost_per(totals.spend_minor, max(totals.leads, totals.leads_reported))


def benchmark(adsets: Iterable[AdSetFacts], *, family: str = "lead") -> Benchmark:
    """The groups handed in, summed. Groups nobody was shown are left out."""
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
    """The benchmark of this group's kind, without this group in it."""
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
    """Whether what this group's results cost is too much to leave alone."""
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
