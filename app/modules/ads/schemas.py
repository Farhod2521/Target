"""Response shapes for the campaigns screens and their switches, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modules.ads.selectors.built import BuiltCampaignType, BuiltConversionEvent
from app.modules.ads.selectors.controls import Controls
from app.modules.ads.selectors.editable import AdContent
from app.modules.ads.selectors.failures import FailureNote
from app.modules.ads.selectors.row_settings import RowSettings


class Tab(BaseModel):
    key: str
    label: str


class ActionOut(BaseModel):
    id: str
    action: str = Field(description="`pause`, `resume`, `budget`, `delete`, ...")
    status: str = Field(description="`pending`, `applied`, `failed`, ...")
    dry_run: bool
    error_message: str = Field(
        description="Why a failed change failed, as the owner reads it."
    )
    created_at: datetime
    applied_at: datetime | None
    revertible: bool = Field(description="May be undone with `.../revert`.")
    dropped: dict[str, Any] = Field(
        default_factory=dict,
        description="What Meta accepted the write without keeping, e.g. `interests`.",
    )


class RowOut(BaseModel):
    id: str
    external_id: str
    provider: str
    name: str
    status: str
    effective_status: str
    delivery: str
    badge: str = Field(description="The state to draw; `delivery` when no badge.")
    badge_label: str
    issue_summary: str = Field(description="Meta's first complaint, empty if none.")
    issues: list[dict[str, Any]] = Field(
        description="Meta's complaints as it sent them."
    )
    recommendations: list[dict[str, Any]]
    early_hours: int = Field(
        description="Hours to wait before a change is advised (learning)."
    )
    controls: Controls | None = Field(description="Which switches this row offers.")
    last_action: ActionOut | None
    deleting: bool
    delete_failure: FailureNote | None = Field(
        description="A delete pressed within the hour that did not go through."
    )
    synced_at: datetime | None


class AdContentOut(BaseModel):
    kind: str
    message: str
    headline: str
    description: str
    link_url: str
    call_to_action: str
    thumbnail_url: str
    page_id: str


class AdOut(RowOut):
    creative_external_id: str
    review_feedback: Any
    is_last: bool = Field(description="The only ad left in its group.")
    content: AdContentOut | None


class AdsetOut(RowOut):
    daily_budget_minor: int | None
    currency: str
    optimization_goal: str
    is_learning: bool
    learning_status: str
    start_time: datetime | None
    end_time: datetime | None
    is_last: bool = Field(description="The only group left in its campaign.")
    settings: RowSettings
    ads: list[AdOut] = Field(
        default=[], description="Only where the groups are opened."
    )


class AccountRef(BaseModel):
    id: str
    name: str
    external_id: str


class CampaignOut(RowOut):
    objective: str
    daily_budget_minor: int | None
    spend_cap_minor: int | None
    currency: str
    created_time: datetime | None
    adset_count: int
    built_here: bool = Field(description="Launched from this cabinet.")
    pending: bool = Field(description="A change is still on its way to Meta.")
    settings: RowSettings | None
    ad_account: AccountRef | None


class GoalGroupOut(BaseModel):
    goal: str
    label: str
    campaign_ids: list[str] = Field(description="Ids from `campaigns`, in order.")


class CountsOut(BaseModel):
    running: int
    stopped: int
    here: int = Field(description="Launched from this cabinet.")
    elsewhere: int = Field(description="Made in Ads Manager.")
    unplaced: int
    pool: int = Field(description="Campaigns under the chosen `source`.")
    total: int


class ListAccountOut(BaseModel):
    id: str
    name: str
    currency: str


class PageRef(BaseModel):
    id: str
    name: str


class CampaignListOut(BaseModel):
    campaigns: list[CampaignOut]
    goal_groups: list[GoalGroupOut]
    counts: CountsOut
    shown: str = Field(description="`running`, `stopped` or `all`, as applied.")
    source: str = Field(description="`here`, `elsewhere` or `all`, as applied.")
    source_fallback: bool = Field(
        description="The chosen source was empty, so `all` is shown instead."
    )
    tabs: list[Tab]
    source_tabs: list[Tab]
    daily_total_minor: int
    daily_total_currency: str
    ad_account: ListAccountOut | None
    shown_page: PageRef | None
    is_connected: bool
    synced_at: datetime | None
    is_stale: bool
    since: str = Field(description="Pass to `GET /campaigns/poll` after a refresh.")
    syncing: bool
    sync_account_ids: list[str] = Field(
        description="Pass joined with commas as `accounts` to the poll."
    )
    auto_refresh: bool = Field(description="Call `POST /campaigns/sync?on_open=true`.")
    tries: int
    retries_left: int
    watching: bool = Field(description="A change is pending: ask again with `waited`.")
    waited: int
    list_poll_seconds: int
    trial_campaigns_left: int | None


class CampaignPollOut(CampaignListOut):
    waiting: bool = Field(
        description="Still refreshing; then only `tries` and `retries_left` come with it."
    )
    gave_up: bool = False
    still_running: bool = False
    sync_failure: str = ""
    sync_partial: str = ""


class SyncOut(CampaignListOut):
    queued: bool = Field(
        description="False on `on_open` when nothing needed a refresh; then nothing "
        "else comes with it."
    )
    message: str = ""


class HistoryOut(BaseModel):
    log: ActionOut
    actor: str = ""
    level: str = ""
    level_label: str
    amount: str
    moment: str
    reason: str


class CampaignDetailOut(BaseModel):
    campaign: CampaignOut
    groups: list[AdsetOut]
    history: list[HistoryOut]
    built_type: BuiltCampaignType | None
    built_event: BuiltConversionEvent | None


class CampaignAdsOut(BaseModel):
    groups: list[AdsetOut]
    watching: bool = Field(description="Something is being deleted: ask again.")
    waited: int
    list_poll_seconds: int


class CampaignHistoryOut(BaseModel):
    history: list[HistoryOut]


class MessageOut(BaseModel):
    message: str


class DeletedOut(MessageOut):
    campaign_id: str = Field(description="Open this campaign again after the delete.")


class ClusterOut(BaseModel):
    level: str
    external_id: str
    delivery: str
    controls: Controls
    action: ActionOut | None


class ControlStateOut(BaseModel):
    level: str = Field(description="`campaign`, `adset` or `ad`.")
    external_id: str
    delivery: str
    controls: Controls
    action: ActionOut | None = Field(description="The latest change on this row.")
    clusters: list[ClusterOut] = Field(
        description="Rows above and below that it moves."
    )
    polling: bool = Field(description="A change is pending: ask `.../state` again.")
    stalled: bool = Field(
        description="Polls ran out with the change still pending: say it is slow."
    )
    failure: FailureNote | None = Field(
        description="Why the latest change on this row failed, when it did."
    )
    tries: int = Field(description="Pass back as `tries`.")
    poll_seconds: int
    refusal: str = Field(description="Why the change was refused; empty if it was not.")


class BudgetFormOut(BaseModel):
    currency: str
    places: int = Field(description="Decimal places of the currency.")
    floor_minor: int
    floor: str = Field(description="The lowest daily budget, formatted.")
    current_minor: int | None
    current: str | None = Field(description="In the main unit, e.g. `12.50`.")
    early_hours: int


class AdRef(BaseModel):
    external_id: str
    name: str
    delivery: str


class AdWordsOut(BaseModel):
    message: str
    headline: str
    description: str


class AssetOut(BaseModel):
    id: str = Field(description="Send as `asset_id` to swap the picture.")
    kind: str
    external_id: str
    name: str
    thumbnail_url: str
    permalink_url: str
    width: int | None
    height: int | None
    is_eligible: bool | None
    ineligible_reason: str


class FormOption(BaseModel):
    external_id: str = Field(description="Send as `lead_form_id`.")
    name: str
    questions: list[Any]


class AdFormsOut(BaseModel):
    current_id: str
    current_name: str
    options: list[FormOption]


class AdEditOut(BaseModel):
    ad: AdRef
    initial: AdWordsOut
    thumbnail_url: str
    can_swap: bool = Field(description="The picture may be changed.")
    library: list[AssetOut]
    ad_forms: AdFormsOut | None = Field(description="Null when the ad opens no form.")
    limits: dict[str, int] = Field(description="Max characters: headline, message.")
    early_hours: int


class BudgetSectionOut(BaseModel):
    level: str
    external_id: str
    can_change: bool
    warns_learning: bool
    currency: str
    places: int
    current: str | None
    current_minor: int | None
    floor_minor: int


class AudienceSectionOut(BaseModel):
    external_id: str
    can_change: bool
    is_learning: bool
    allows_gender: bool
    age_min: int
    age_max: int
    age_bounds: list[int]
    genders: list[int] = Field(description="[] everybody, [1] men, [2] women.")
    offers_radius: bool
    radius_km: int | None
    radius_bounds: list[int]
    has_interests: bool


class LimitsSectionOut(BaseModel):
    can_change: bool
    offers_end_time: bool
    offers_spend_cap: bool
    end_date: date | None
    earliest_end_date: date
    spend_cap: str | None
    currency: str
    timezone: str


class SectionsOut(BaseModel):
    budget: BudgetSectionOut | None = Field(
        None, description="Absent when not editable."
    )
    audience: AudienceSectionOut | None = Field(
        None, description="Absent when not editable."
    )
    limits: LimitsSectionOut | None = Field(
        None, description="Absent when not editable."
    )


class CampaignRef(BaseModel):
    id: str
    name: str


class CampaignEditOut(BaseModel):
    campaign: CampaignRef
    groups: int
    sections: SectionsOut
    early_hours: int


class CampaignEditSaveOut(BaseModel):
    queued: list[str] = Field(description="Sections sent to Meta.")
    refused: dict[str, str] = Field(description="Section -> why it was not sent.")
    adjustments: list[dict[str, str]] = Field(
        default_factory=list,
        description="What the rules changed of what was asked: `field`, `reason`, `detail`.",
    )
    message: str


class PreviewFrame(BaseModel):
    src: str
    width: int
    height: int


class PreviewOut(BaseModel):
    external_id: str
    name: str
    content: AdContent | None = Field(
        description="The mirror's own card, always there."
    )
    preview: PreviewFrame | None = Field(description="Meta's frame once it arrives.")
    polling: bool = Field(description="Ask again with `tries`.")
    tries: int
    poll_seconds: int
    gave_up: bool


__all__ = [
    "AdEditOut",
    "BudgetFormOut",
    "CampaignAdsOut",
    "CampaignDetailOut",
    "CampaignEditOut",
    "CampaignEditSaveOut",
    "CampaignHistoryOut",
    "CampaignListOut",
    "CampaignPollOut",
    "ControlStateOut",
    "DeletedOut",
    "MessageOut",
    "PreviewOut",
    "SyncOut",
]
