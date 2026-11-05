"""What one metric is, what it is computed from, and what it answers.

Every metric on every screen has the same shape: a key, the words for it,
the levels and networks it exists at, and one function from the figures to
an answer. A network's own metric is the same shape in its own module; it is
never a Meta metric with a flag on it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from adskit import MinorUnits

from core.metrics.outcomes import Outcome

Level = Literal["campaign", "adset", "ad"]
Network = Literal["meta", "google", "chatgpt"]
Group = Literal[
    "money", "result", "delivery", "engagement", "video", "quality", "sales"
]
Unit = Literal["money", "count", "percent", "ratio", "ranking"]

ALL_LEVELS: Final[frozenset[Level]] = frozenset({"campaign", "adset", "ad"})
AD_ONLY: Final[frozenset[Level]] = frozenset({"ad"})
ALL_NETWORKS: Final[frozenset[Network]] = frozenset({"meta", "google", "chatgpt"})
META_ONLY: Final[frozenset[Network]] = frozenset({"meta"})

# Why a metric has no number. Every ``–`` on a screen carries one of these,
# so the reader is told whether to wait, to look elsewhere or to fix the ad.
Missing = Literal[
    # The network has not been read for this range yet.
    "not_read",
    # Read for the days but not for the range as a whole: reach and unique
    # clicks count people, and people cannot be added up across days.
    "not_asked",
    # The division has nothing under it: no impressions, no clicks, no leads.
    "no_base",
    # A cost with nothing spent, which would read as "free".
    "no_spend",
    # A messaging campaign sends nobody to a link.
    "no_link",
    # An image advert has no video to hold anybody.
    "not_video",
    # The network ranks an advert only past 500 impressions.
    "few_impressions",
    # The figure belongs to a different goal: a form conversion on a
    # campaign bought for reach.
    "other_goal",
    # The result of this goal is counted somewhere this product cannot read.
    "uncounted",
    # The metric does not exist at this level or on this network.
    "not_here",
    # Qualified leads and sales are the CRM's word, and no CRM is on here.
    "no_crm",
]

type Value = MinorUnits | int | Decimal | str


@dataclass(frozen=True, slots=True)
class Figures:
    """Everything a range of one object was measured to be.

    Counts are summed across days. ``reach`` and ``unique_link_clicks`` are
    the exception: they count people, so they are read for the range as a
    whole and are ``None`` where nobody asked. The rankings are the last
    day's, as the network shows them.
    """

    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    link_clicks: int = 0
    landing_page_views: int = 0
    # The network's own "Results": the ad set's goal and nothing else.
    results: int = 0
    leads_ours: int = 0
    leads_reported: int = 0
    recallers: int = 0
    profile_visits: int = 0
    qualified: int = 0
    purchases_site: int = 0
    purchase_value_site_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009
    purchases_crm: int = 0
    video_plays: int = 0
    video_views_3s: int = 0
    video_thruplays: int = 0
    reach: int | None = None
    unique_link_clicks: int | None = None
    quality_ranking: str = ""
    engagement_rate_ranking: str = ""
    conversion_rate_ranking: str = ""
    # Whether the network has been read for this range at all. ``False``
    # turns every network figure into ``not_read``; our own counts stay.
    read: bool = True
    # Whether a CRM is on for the object's account. ``False`` turns every
    # qualified and CRM-sold figure into ``no_crm`` rather than nought.
    crm: bool = True


@dataclass(frozen=True, slots=True)
class Setting:
    """What the figures belong to: the level, the network, the goal."""

    level: Level
    network: Network = "meta"
    outcome: Outcome = "lead"


@dataclass(frozen=True, slots=True)
class Answer:
    """One metric's value, or the reason there is none."""

    value: Value | None = None
    missing: Missing | None = None

    @property
    def known(self) -> bool:
        return self.value is not None


def missing(why: Missing) -> Answer:
    return Answer(missing=why)


def known(value: Value | None, *, otherwise: Missing = "no_base") -> Answer:
    """A computed value, or ``otherwise`` where the arithmetic gave nothing."""
    return Answer(value=value) if value is not None else Answer(missing=otherwise)


def cost(value: MinorUnits | None, *, spend_minor: int) -> Answer:
    """A cost, saying whether it was the spend or the count that was missing."""
    if value is not None:
        return Answer(value=value)
    return missing("no_spend" if spend_minor <= 0 else "no_base")


Formula = Callable[[Figures, Setting], Answer]


@dataclass(frozen=True, slots=True)
class Metric:
    """One metric a screen may show."""

    key: str
    label: str
    hint: str
    group: Group
    unit: Unit
    formula: Formula
    levels: frozenset[Level] = ALL_LEVELS
    networks: frozenset[Network] = ALL_NETWORKS
    lower_is_better: bool = False
    # What a healthy value looks like, in words, for the column's tooltip.
    norm: str = ""
    # Whether the figure comes from the network, so ``read=False`` hides it.
    from_network: bool = True
    # Whether it needs the CRM's verdicts, so ``crm=False`` hides it.
    from_crm: bool = False

    def exists(self, setting: Setting) -> bool:
        return setting.level in self.levels and setting.network in self.networks


__all__ = [
    "AD_ONLY",
    "ALL_LEVELS",
    "ALL_NETWORKS",
    "META_ONLY",
    "Answer",
    "Figures",
    "Formula",
    "Group",
    "Level",
    "Metric",
    "Missing",
    "Network",
    "Setting",
    "Unit",
    "Value",
    "cost",
    "known",
    "missing",
]
