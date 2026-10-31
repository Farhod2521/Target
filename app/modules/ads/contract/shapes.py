"""The ads screens' answers, key for key as ``packages/api/src/campaigns.ts`` reads them."""

from typing import Literal

from pydantic import Field

from app.common.contract import Camel, Money, Refusal
from app.modules.ads.contract.words import Goal, Kind, Origin, Status

SyncReason = Literal["unusable", "rate_limited", "busy", "truncated", "other"]


class NetworkRef(Camel):
    id: str
    letter: str
    name: str


class Learning(Camel):
    hours: int
    total: int
    ready_at: str


class Controls(Camel):
    can_pause: bool
    can_resume: bool
    can_budget: bool
    learning: bool = Field(description="A change restarts the network's learning.")
    early_hours: int
    watched: bool | None = Field(
        None, description="From an account the owner did not pick: never changed here."
    )


class RowFigures(Camel):
    results: int
    unit_cost: Money | None
    spent: Money


class ListedCampaign(Camel):
    id: str
    external_id: str
    name: str
    goal: Goal
    kind: Kind
    status: Status
    network: NetworkRef
    origin: Origin
    daily_budget: Money
    audience: str
    ends_at: str | None
    total_limit: Money | None
    metrics: RowFigures | None
    quiet_days: int | None = None
    learning: Learning | None = None
    sending: bool | None = None
    problem: str | None = None
    deleting: bool | None = None
    last_action: Literal["failed", "dry_run"] | None = None
    group_count: int | None = None
    controls: Controls
    ad_count: int | None
    created_at: str
    launched_at: str | None


class SyncState(Camel):
    synced_at: str | None
    stale: bool
    failure: SyncReason | None = None
    late: bool | None = None
    partial: SyncReason | None = None


class Access(Camel):
    read_only: bool
    lapse_until: str | None = Field(description="ISO day the stopped adverts go.")


class Sources(Camel):
    all: int
    here: int
    network: int
    other_account: int = Field(alias="other_account")


class DayRange(Camel):
    since: str
    until: str
    earliest: str
    today: str
    time_zone: str | None = None


class StartedAd(Camel):
    campaign_id: str
    business: str
    goal: str
    budget: Money | None
    first: bool


class Summary(Camel):
    daily_budget: Money
    spent: Money
    running: int


class TrialOffer(Camel):
    name: str
    price: Money
    days: int


class Trial(Camel):
    limit: int
    left: int
    offer: TrialOffer | None


class Counts(Camel):
    running: int
    paused: int
    all: int


class CampaignList(Camel):
    state: Literal["ready", "reading", "not_connected"]
    reading_from: str | None = None
    updated_at: str
    sync: SyncState
    auto_refresh: bool
    access: Access
    unplaced: int
    source_fallback: bool
    sources: Sources
    range: DayRange
    started: StartedAd | None
    summary: Summary
    trial: Trial | None
    draft: None = None
    counts: Counts
    total: int
    campaigns: list[ListedCampaign]


class CampaignAd(Camel):
    id: str
    external_id: str
    position: int
    format: Literal["image", "video"]
    duration: int | None = None
    name: str | None = None
    thumb: str | None = None
    headline: str | None = None
    text: str
    description: str | None = None
    cta: str | None = None
    link: str | None = None
    status: Status
    results: int
    unit_cost: Money | None
    spent: Money | None
    controls: Controls | None = None
    is_last: bool | None = None
    deleting: bool | None = None
    can_swap: bool | None = Field(
        None, description="False: the words live on the page's post, changed there."
    )


class AdGroup(Camel):
    external_id: str
    name: str
    status: Status
    daily_budget: Money | None
    min_budget: Money | None
    controls: Controls
    is_last: bool
    deleting: bool | None = None
    last_action: Literal["failed", "dry_run"] | None = None
    ads: list[CampaignAd]


class CampaignTree(Camel):
    split: bool
    groups: list[AdGroup]


class PanelCard(Camel):
    key: str
    label: str
    display: str
    trend: Literal["up", "down", "flat"]
    delta_pct: int
    good: bool
    hint: str | None = None
    basis_note: str | None = None


class PanelSeries(Camel):
    key: str
    label: str
    labels: list[str]
    values: list[float]
    floor: str
    peak: str


class FunnelStage(Camel):
    label: str
    value: str
    share_pct: int | None
    note: str


class Funnel(Camel):
    heading: str
    lid: str
    steps: list[FunnelStage]


class PanelTab(Camel):
    key: str
    label: str
    empty: bool
    cards: list[PanelCard]
    series: list[PanelSeries]
    mismatch: str | None = None
    funnel: Funnel | None


class Panel(Camel):
    has_choice: bool
    has_figures: bool
    note: str | None = None
    periods: list[PanelTab]


class Social(Camel):
    reactions: int
    comments: int
    shares: int
    saves: int


class Quality(Camel):
    creative: str | None = None
    engagement: str | None = None
    conversion: str | None = None


class WatchMark(Camel):
    at: int
    share: int


class Watch(Camel):
    plays: int
    points: list[WatchMark]


class CreativeView(Camel):
    external_id: str
    place: int | None = None
    name: str | None = None
    thumb: str | None = None
    headline: str
    message: str
    status: Status | None
    kind_label: str | None = None
    own_leads: int | None = None
    results: int
    cost: str | None = None
    verdict: str | None = None
    spend: str
    spend_share: int
    impressions: int | None = None
    link_clicks: int | None = None
    link_ctr: str | None = None
    days: int
    social: Social | None = None
    quality: Quality | None = None
    watch: Watch | None = None
    missing: bool | None = None


class CreativesReport(Camel):
    since: str
    until: str
    average: str | None = None
    cost_label: str
    result_heading: str
    has_figures: bool
    alone: bool
    min_results: int
    best_results: int
    note: str | None = None
    ranked: list[CreativeView]
    barren: list[CreativeView]
    weak: list[CreativeView]
    thin: list[CreativeView]
    waiting: list[CreativeView]


class HistoryRow(Camel):
    id: str
    text: str
    at: str
    by: Literal["you_changed", "you_confirmed", "you", "system", "network"]
    note: str | None = None
    level: str | None = None
    status: Literal["applied", "failed", "pending", "cancelled"] | None = None
    dry_run: bool | None = None


class Problem(Camel):
    text: str
    fix: str


class Stats(Camel):
    unit_cost: Money
    unit_cost_delta_pct: int | None
    spent: Money
    results: int
    results_delta_pct: int | None
    impressions: int
    ctr: float = Field(description="A fraction: 0.019 is 1.9%.")


class Note(Camel):
    tone: Literal["reco", "warn", "danger"]
    text: str
    where: str | None = None


class DetailSettings(Camel):
    type_en: str
    result_event: str
    place: str
    starts_at: str | None
    limit: Money | None = Field(description="None: no spending limit.")
    form: str | None


class DetailGroup(Camel):
    id: str
    external_id: str
    name: str
    daily_budget: Money
    status: Status
    controls: Controls
    min_budget: Money


class CampaignDetail(Camel):
    id: str
    name: str
    kind: Kind
    goal: Goal
    status: Status
    network: NetworkRef
    parent_name: str
    daily_budget: Money
    audience: str
    ends_at: str | None
    learning: Learning | None
    problem: Problem | None
    stats: Stats | None
    daily: None = None
    ads: list[CampaignAd]
    notes: list[Note]
    settings: DetailSettings
    groups: list[DetailGroup] | None
    history: list[HistoryRow]
    controls: Controls
    access: Access
    panel: Panel
    creatives: CreativesReport | None


class Fix(Camel):
    label: str
    url: str


class ControlFailure(Camel):
    text: str
    fix: Fix | None
    explanation_html: str | None = Field(
        None, description="Why the network refused it and what to do, as HTML."
    )
    explaining: bool | None = Field(
        None, description="That answer is being written: ask `/state` again."
    )
    refusal: Refusal | None = None


class ControlAction(Camel):
    id: str
    status: str
    dry_run: bool
    revertible: bool


class ControlState(Camel):
    level: Literal["campaign", "adset", "ad"]
    external_id: str
    pending: bool = Field(description="Still on its way: ask `/state` again.")
    stalled: bool
    failure: ControlFailure | None
    action: ControlAction | None
    tries: int
    poll_seconds: int
    refused: str | None = Field(None, description="Not sent at all: the sentence why.")


class EditGroup(Camel):
    external_id: str
    name: str


EditLock = Literal["learning", "closed"]


class EditLocks(Camel):
    budget: EditLock | None
    audience: EditLock | None
    limits: Literal["ended"] | None


class EditAudience(Camel):
    id: str
    name: str
    on: bool


class CampaignEdit(Camel):
    id: str
    name: str
    kind: Kind
    network: NetworkRef
    currency: str
    daily_budget: float = Field(description="Major units, as the input shows them.")
    min_budget: float
    presets: list[int]
    spent7d: Money = Field(alias="spent7d")
    spent_total: Money
    unit_cost: Money | None
    place: str
    age_min: int
    age_max: int
    age_bounds: list[int]
    gender: Literal["all", "female", "male"]
    audiences: list[EditAudience]
    reach: list[int]
    ends_at: str | None
    limit: float | None
    group: EditGroup | None
    split: bool
    locks: EditLocks
    early_hours: int


class CampaignRef(Camel):
    id: str
    name: str


class LibraryItem(Camel):
    id: str
    name: str
    kind: Literal["image", "video"]
    thumb: str | None


class FormOption(Camel):
    id: str
    name: str
    questions: list[str]


class AdForms(Camel):
    current_name: str
    options: list[FormOption]


class WordLimits(Camel):
    message: int
    headline: int


class AdEdit(Camel):
    external_id: str
    campaign: CampaignRef
    network: NetworkRef
    current: str
    can_swap: bool = Field(description="False: the words live on the page's post.")
    message: str
    headline: str
    description: str
    limits: WordLimits
    library: list[LibraryItem]
    forms: AdForms | None
    early_hours: int


class GroupSource(Camel):
    external_id: str
    name: str


class NewGroupForm(Camel):
    """Where a new group goes, what it may copy, and who pays for it."""

    campaign: CampaignRef
    network: NetworkRef
    budget_at: Literal["campaign", "adset"]
    currency: str
    min_budget: float
    groups: list[GroupSource]


class NewAdForm(AdEdit):
    """The advert a new one starts from; ``external_id`` names it as ``source``."""

    group: str
    name: str
    warns_learning: bool = Field(
        description="Adding an advert restarts this group's learning."
    )


class AdditionStarted(Camel):
    action_id: str = Field(description="Follow it at `/campaigns/actions/{id}`.")


class PageName(Camel):
    name: str
    initials: str


class PreviewAd(CampaignAd):
    title: str
    cta: str
    file: str
    site: str
    tagline: str
    offer: str
    description: str
    page: PageName


class Sibling(Camel):
    external_id: str
    position: int


class Frame(Camel):
    state: Literal["loading", "ready", "gave_up"]
    src: str | None = None
    height: int | None = None


class AdPreview(Camel):
    campaign: CampaignRef
    siblings: list[Sibling]
    ad: PreviewAd
    content: Literal["loaded", "post", "pending"]
    frame: Frame


class ManagerRow(Camel):
    level: Literal["campaign", "adset", "ad"]
    id: str = Field(description="The network's id of this row.")
    campaign_id: str = Field(description="This product's id of the campaign.")
    campaign_external_id: str
    adset_external_id: str | None
    name: str
    status: Status
    kind: Kind
    network: NetworkRef
    budget: Money | None
    budget_at: Literal["campaign", "adset"]
    results: int
    unit_cost: Money | None
    spent: Money | None
    impressions: int
    reach: int
    clicks: int
    controls: Controls
    problem: str | None = None


class ManagerData(Camel):
    campaigns: list[ManagerRow]
    adsets: list[ManagerRow]
    ads: list[ManagerRow]


__all__ = [
    "Access",
    "AdEdit",
    "AdGroup",
    "AdPreview",
    "CampaignAd",
    "CampaignDetail",
    "CampaignEdit",
    "CampaignList",
    "CampaignTree",
    "ControlState",
    "Controls",
    "Counts",
    "CreativesReport",
    "DayRange",
    "HistoryRow",
    "Learning",
    "ListedCampaign",
    "ManagerData",
    "NetworkRef",
    "Panel",
    "RowFigures",
    "Sources",
    "StartedAd",
    "Summary",
    "SyncState",
    "Trial",
    "TrialOffer",
]
