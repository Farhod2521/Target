"""What a decision is allowed to look at."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from adskit import ProviderName

from core.agent.ad_facts import AdFacts, LibraryImage
from core.agent.contracts import Policy, ProviderAdvice
from core.agent.funnel import Funnel, Landing
from core.metrics import Outcome, SegmentComparison, SegmentFigures, Totals

_ACTIVE = "active"

_SWITCHED_OFF = frozenset({"paused", "paused_above", "finished"})


def ctr_bp(*, clicks: int, impressions: int) -> int | None:
    """Clicks per ten thousand impressions, or nothing to divide by."""
    if impressions <= 0:
        return None
    return round(clicks * 10_000 / impressions)


@dataclass(frozen=True, slots=True)
class Half:
    """One half of the window, for the questions that need a direction."""

    days: int = 0
    impressions: int = 0
    link_clicks: int = 0
    frequency: int = 0

    @property
    def link_ctr_bp(self) -> int | None:
        """This half's link click-through rate, in ten-thousandths."""
        return ctr_bp(clicks=self.link_clicks, impressions=self.impressions)


@dataclass(frozen=True, slots=True)
class AdSetFacts:
    """One ad set, as the window saw it."""

    external_id: str
    campaign_external_id: str
    name: str
    delivery: str
    totals: Totals
    days_with_spend: int = 0
    is_learning: bool = False
    learning_limited: bool = False
    daily_budget_minor: int | None = None
    budget_moved: bool = False
    targeting: Mapping[str, Any] = field(default_factory=dict)
    floor_minor: int = 0
    stopped_by_agent: bool = False
    early: Half = field(default_factory=Half)
    late: Half = field(default_factory=Half)
    segments: SegmentComparison = field(default_factory=SegmentComparison)
    ads: tuple["AdFacts", ...] = ()
    counts_leads: bool = False
    outcome: Outcome = "none"
    is_ours: bool = False
    issue_codes: tuple[str, ...] = ()
    unusable_audience_ids: tuple[str, ...] = ()
    advice: tuple[ProviderAdvice, ...] = ()
    funnel: Funnel = field(default_factory=Funnel)
    landing: Landing = field(default_factory=Landing)
    slices: Mapping[str, tuple[SegmentFigures, ...]] = field(default_factory=dict)

    @property
    def budgeted_minor(self) -> int:
        """What this ad set was allowed to spend over the window."""
        if not self.daily_budget_minor or self.days_with_spend <= 0:
            return 0
        return self.daily_budget_minor * self.days_with_spend

    @property
    def spend_share(self) -> int:
        """How much of its allowance it actually used, as a percentage."""
        allowance = self.budgeted_minor
        if allowance <= 0:
            return 0
        return round(self.totals.spend_minor / allowance * 100)


@dataclass(frozen=True, slots=True)
class AccountFacts:
    """The window, and every ad set in it."""

    provider: ProviderName
    currency: str
    window_days: int
    totals: Totals
    adsets: tuple[AdSetFacts, ...] = ()
    lead_totals: Totals = field(default_factory=Totals)
    library: tuple[LibraryImage, ...] = ()

    def in_campaign(self, campaign_external_id: str) -> tuple[AdSetFacts, ...]:
        """Every ad set under one campaign, whatever its state."""
        return tuple(
            item
            for item in self.adsets
            if item.campaign_external_id == campaign_external_id
        )

    def only_ours(self) -> "AccountFacts":
        """The same account with the campaigns built elsewhere removed."""
        return replace(self, adsets=tuple(item for item in self.adsets if item.is_ours))

    def only_lead_goals(self) -> "AccountFacts":
        """The same account with the ad sets that cannot bring a lead removed."""
        return replace(
            self, adsets=tuple(item for item in self.adsets if item.counts_leads)
        )


def troubled(item: AdSetFacts) -> bool:
    """Whether the provider has stopped this group over a fault of its own."""
    return (
        bool(item.issue_codes) and item.delivery != _ACTIVE and not switched_off(item)
    )


def switched_off(item: AdSetFacts) -> bool:
    """Whether the owner, or a campaign above it, has this group switched off."""
    return item.delivery in _SWITCHED_OFF


def judgeable(item: AdSetFacts, policy: Policy) -> bool:
    """Whether this ad set has earned an opinion yet."""
    return (
        item.delivery == _ACTIVE
        and not item.is_learning
        and item.days_with_spend >= policy.min_days
    )


__all__ = [
    "AccountFacts",
    "AdFacts",
    "AdSetFacts",
    "Half",
    "LibraryImage",
    "ctr_bp",
    "judgeable",
    "switched_off",
    "troubled",
]
