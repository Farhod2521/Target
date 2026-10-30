"""The ads screens' answers, key for key as ``packages/api/src/campaigns.ts`` reads them."""

from typing import Literal

from pydantic import Field

from app.common.contract import Camel, Money
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


class CampaignRow(Camel):
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
    campaigns: list[CampaignRow]


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


__all__ = [
    "Access",
    "AdGroup",
    "CampaignAd",
    "CampaignList",
    "CampaignRow",
    "CampaignTree",
    "Controls",
    "Counts",
    "DayRange",
    "Learning",
    "NetworkRef",
    "RowFigures",
    "Sources",
    "StartedAd",
    "Summary",
    "SyncState",
    "Trial",
    "TrialOffer",
]
