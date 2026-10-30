from dataclasses import dataclass
from typing import Any, Literal

Trend = Literal["up", "down", "flat"]


@dataclass(frozen=True, slots=True)
class Kpi:
    key: str
    label: str
    display: str
    delta_pct: int
    trend: Trend
    is_good: bool
    hint: str


@dataclass(frozen=True, slots=True)
class OutcomeBlock:
    kind: str
    label: Any
    cost_label: Any
    hint: Any
    headline_note: Any
    count: str
    cost: str
    spend: str
    spend_minor: int
    delta_pct: int = 0
    trend: Trend = "flat"
    is_good: bool = False
    note: Any = ""
    shown: str = ""
    impressions: int = 0
    shown_pct: int = 0
    shown_before_pct: int = 0
    slice: int = 0
    spend_pct: int = 0

    @property
    def countable(self) -> bool:
        return not self.note


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float
    label: str
    display: str


@dataclass(frozen=True, slots=True)
class Series:
    key: str
    label: str
    polyline: str
    points: tuple[Point, ...]
    peak: str
    floor: str


@dataclass(frozen=True, slots=True)
class FunnelStep:
    label: str
    value: str
    share_pct: int | None
    note: str


@dataclass(frozen=True, slots=True)
class CampaignRow:
    name: str
    delivery: str
    delivery_label: str
    spend: str
    spend_minor: int
    leads: int
    qualified: int
    cpl: str
    cpql: str
    note: Any
    results: int = 0
    result_label: Any = ""
    result_cost: str = ""
    result_cost_label: Any = ""
    result_source: Any = ""
    kind: str = "lead"
    uncounted_label: Any = ""


@dataclass(frozen=True, slots=True)
class KindView:
    kind: str
    label: Any
    series: tuple[Series, ...]
    funnel: tuple[FunnelStep, ...]
    campaigns: int = 0


@dataclass(frozen=True, slots=True)
class Period:
    key: str
    label: str
    spend: str
    leads: int
    qualified: int
    cpl: str
    cpql: str
    reported_leads: int
    reported_cpl: str
    quality_pct: int
    kpis: tuple[Kpi, ...]
    outcomes: tuple[OutcomeBlock, ...]
    series: tuple[Series, ...]
    funnel: tuple[FunnelStep, ...]
    campaigns: tuple[CampaignRow, ...]
    campaign_count: int = 0
    days: int = 1
    in_progress: bool = False
    spend_minor: int = 0
    shown: str = "0"
    shown_total: int = 0
    scoped_to: Any = ""
    views: tuple[KindView, ...] = ()
    unknown_after: str = ""

    @property
    def view_kinds(self) -> tuple[str, ...]:
        return tuple(one.kind for one in self.views)

    @property
    def is_quiet(self) -> bool:
        return not self.spend_minor and (not self.leads)

    @property
    def only_reported(self) -> bool:
        if self.leads or not self.reported_leads:
            return False
        head = self.headline
        return head is None or head.kind in {"lead", "none"}

    @property
    def headline(self) -> "OutcomeBlock | None":
        return self.outcomes[0] if self.outcomes else None


@dataclass(frozen=True, slots=True)
class LeadRow:
    pk: str
    name: str
    city: str
    phone_masked: str
    when: str
    campaign: str
    verdict: str


@dataclass(frozen=True, slots=True)
class Decision:
    when: str
    action: str
    target: str
    reason: str
    actor: str


@dataclass(frozen=True, slots=True)
class Notice:
    level: str
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class SourceBar:
    label: str
    share_pct: int
    leads: int
    total_pct: int = 0


@dataclass(frozen=True, slots=True)
class SegmentRow:
    label: str
    cpl: str
    index: int
    compare: str
    leads: int
    spend: str
    spend_share: int


@dataclass(frozen=True, slots=True)
class SegmentBlock:
    key: str
    title: str
    days: int
    leads: int
    min_leads: int
    best_leads: int
    ranked: tuple[SegmentRow, ...]
    barren: tuple[SegmentRow, ...]
    has_forms: bool = True


@dataclass(frozen=True, slots=True)
class ShowingRow:
    label: str
    shown: str
    spend: str
    share_pct: int
    cost: str = ""


@dataclass(frozen=True, slots=True)
class CutTab:
    key: str
    label: Any
    days: int = 0
    block: SegmentBlock | None = None
    showing: tuple[ShowingRow, ...] = ()
    bars: tuple[SourceBar, ...] = ()


@dataclass(frozen=True, slots=True)
class KindCuts:
    kind: str
    tabs: tuple[CutTab, ...]


@dataclass(frozen=True, slots=True)
class Dashboard:
    currency: str
    period: Period
    leads: tuple[LeadRow, ...]
    decisions: tuple[Decision, ...]
    by_city: tuple[SourceBar, ...]
    by_city_source: str
    by_hour: tuple[SourceBar, ...]
    segments: tuple[SegmentBlock, ...]
    has_run: bool
    elsewhere_spend: str = ""
    other_currency: tuple[str, ...] = ()
    cuts: tuple[KindCuts, ...] = ()

    @property
    def segments_priced(self) -> bool:
        return any(block.ranked for block in self.segments)


@dataclass(frozen=True, slots=True)
class Card:
    key: str
    label: str
    hint: str
    display: str
    basis_note: str = ""
    delta_pct: int = 0
    trend: Trend = "flat"
    is_good: bool = False


@dataclass(frozen=True, slots=True)
class CardGroupBlock:
    key: str
    label: str
    cards: tuple[Card, ...]


@dataclass(frozen=True, slots=True)
class PanelPeriod:
    key: str
    label: str
    groups: tuple[CardGroupBlock, ...]
    series: tuple[Series, ...] = ()
    funnel: tuple[FunnelStep, ...] = ()
    lid: Any = ""
    funnel_heading: Any = ""
    mismatch: Any = ""

    @property
    def is_empty(self) -> bool:
        return not self.groups


@dataclass(frozen=True, slots=True)
class CampaignPanel:
    periods: tuple[PanelPeriod, ...] = ()
    has_figures: bool = False
    has_choice: bool = True
    note: Any = ""


@dataclass(frozen=True, slots=True)
class Chip:
    key: str
    label: str
    display: str
    note: str = ""
    source: str = ""
    # The figure itself: minor units for money, a count otherwise; None when
    # there is none (a cost with no results). ``display`` is its words.
    value: float | None = None


@dataclass(frozen=True, slots=True)
class ChipRow:
    campaign_id: str
    chips: tuple[Chip, ...]
    quiet: str = ""
    # The days of the range nothing was spent, when ``quiet`` says so.
    quiet_days: int | None = None


@dataclass(frozen=True, slots=True)
class AdChips:
    ad_id: str
    chips: tuple[Chip, ...]
