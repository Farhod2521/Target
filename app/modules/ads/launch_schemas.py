"""Response shapes for the launch wizard's review step, for the API reference only.

Attached with ``responses=``, as :mod:`app.modules.ads.schemas` is: the routes
still return plain dicts, so a shape that drifts from these never fails a
request. The PG tests validate real answers against them (``extra="forbid"``),
which is what keeps the generated TypeScript types honest.

The draft's own sections (an audience as chosen, an interest as offered) are
loose dicts here: they are whatever the AI and the editor wrote, and their
keys are named in the field descriptions.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ads.selectors.advice import Recommendation
from app.modules.ads.selectors.campaign_type import (
    CampaignTypeCard,
    CampaignTypeChoices,
)
from app.modules.ads.selectors.conversion_event import (
    ConversionEventCard,
    ConversionEventChoices,
)
from app.modules.ads.selectors.delivery_options import CostCapChoice, DeliveryChoices
from app.modules.ads.selectors.launches import IdentityHold
from app.modules.ads.selectors.lead_form import EndingChoice, FormDepthChoice
from app.modules.ads.selectors.pixel import PixelOption
from app.modules.ads.selectors.preparing import Preparing, WaitStage
from app.modules.ads.selectors.proposal_changes import ProposalChange
from app.modules.ads.selectors.quality import QualityOffer
from app.modules.ads.selectors.schedule import StartDay
from app.modules.ads.selectors.tracking import ButtonChoices, UrlTagsChoice
from app.modules.ads.summaries import AudienceSummary, FormSummary, NameList
from app.modules.leads.selectors.reads import FormOption as PageFormOption
from core.agent.copy_check import CopyFinding


class Shape(BaseModel):
    """Every key the route sends is named here, and nothing else."""

    model_config = ConfigDict(extra="forbid")


class LaunchHeadOut(Shape):
    id: str
    provider: str
    status: str = Field(
        description="`draft`, `building`, `ready`, `creating`, `created`, `failed`, `rolled_back`"
    )
    step: str = Field(description="The pipeline's step: `asking`, `llm`, `creating`…")
    progress: int
    currency: str
    daily_budget_minor: int | None
    start_date: date | None
    end_date: date | None
    resume: str = Field(
        description="Where the wizard continues: `plan`, `media`, `review`."
    )
    created_at: datetime
    updated_at: datetime


class ReachOut(Shape):
    lower: int | None = None
    upper: int | None = None
    is_narrow: bool | None = None
    is_empty: bool | None = None
    unknown: bool | None = None
    at: datetime | None


class ReviewStateOut(Shape):
    id: str
    status: str
    step: str
    progress: int
    error_code: str
    error_message: str
    error_detail: dict[str, Any]
    preparing: Preparing | None = Field(description="While `building` only.")
    can_retry: bool
    posts_not_promoted: list[int] = Field(description="1-based advert numbers.")
    delivery_ready: bool | None = None
    created_ad_id: str | None = None
    delivery_started: bool | None = None
    delivery_note: str | None = None
    launch_note: str | None = None
    delivery_pending: bool | None = None
    creating_stages: list[WaitStage]
    failed_creating: bool
    can_launch: bool
    launch_blocker: str = Field(
        description="The one precondition «Ishga tushirish» is refused on, or empty."
    )
    group_least: str
    needs_fix_first: bool
    show_proposal: bool
    answers_complete: bool
    proposal_changes: list[ProposalChange]
    has_stranded: bool
    cleanup_state: str
    page_terms_url: str
    ads_manager_url: str
    billing_url: str
    identity_hold: IdentityHold | None
    cap_not_sent: bool
    reach: ReachOut | None
    tries: int
    keep_polling: bool


class ChoiceOut(Shape):
    value: str
    label: str
    note: str


class TargetRowOut(Shape):
    key: str
    field: str
    label: str
    reason: str
    role: str = Field(description="`include`, `exclude`, or empty.")
    disabled: bool


class PinnedPlacementOut(Shape):
    label: str
    note: str


class AudienceOut(Shape):
    chosen: dict[str, Any] = Field(
        description="As saved: `age_min`, `age_max`, `genders` ([1] men, [2] women), "
        "`targeting_mode`, `placement_mode`, the geo keys."
    )
    card: AudienceSummary
    mode: str
    mode_source: str = Field(description="`ai` or `owner`.")
    exact_age_mode: str
    automatic_max_age_min: int
    automatic_age_max: int
    modes: list[ChoiceOut]
    placement_mode: str
    placement_source: str
    placement_modes: list[ChoiceOut]
    placement_pinned: PinnedPlacementOut | None
    lead_buying: str = Field(description="`volume` or `quality`.")
    lead_buying_modes: list[ChoiceOut]
    quality_offer: QualityOffer
    buying_advice: Recommendation | None
    geo: dict[str, Any] = Field(description="`mode` (`country`, `places`, `around`), …")
    geo_places: list[dict[str, str]] = Field(description="`key`, `name`, `type`.")
    geo_pending: list[str]
    geo_unmatched: list[str]
    geo_areas: list[dict[str, str]]
    geo_chosen_areas: list[str]
    geo_limit: int
    targets: list[TargetRowOut]


class InterestsOut(Shape):
    offered: list[dict[str, Any]] = Field(
        description="`query`, `name`, `external_id`, …"
    )
    chosen_queries: list[str]
    extra: list[dict[str, Any]]
    confirmed_queries: list[str]
    dropped: list[Any]
    stand_in: list[dict[str, Any]]
    card: NameList


class TraitsOut(Shape):
    offered: list[dict[str, Any]]
    chosen_queries: list[str]
    dropped: list[Any]
    card: NameList


class AssetCardOut(Shape):
    id: str
    kind: str = Field(description="`image`, `video`, `ig_image`, `ig_video`.")
    name: str
    external_id: str
    thumbnail_url: str
    is_instagram: bool


class VariantCardOut(Shape):
    id: str
    position: int = Field(description="0-based; renumbered when an advert is removed.")
    asset: AssetCardOut | None
    upload_name: str
    file_url: str
    is_upload: bool
    is_video: bool
    primary_text: str
    headline: str
    description: str
    is_post: bool
    words_touched: bool
    is_uploading: bool
    upload_failed: bool
    brief: str
    copy_notes: list[CopyFinding]
    ad_name: str
    ad_named: bool
    post_route: str
    post_route_note: str


class DestinationOut(Shape):
    button_action: str
    shows_a_button: bool
    link: str
    opens_chat: bool
    chat_channel_label: str
    welcome_text: str
    chat_questions: list[str]
    phone: str
    profile: str
    promotes_post: bool
    post_caption: str


class LeadFormOut(Shape):
    questions: list[dict[str, Any]] = Field(description="`kind`, `label`, `options`, …")
    chosen_kinds: list[str]
    custom_kinds: list[str]
    standard_kinds: list[str]
    max_options: int
    max_custom: int
    options_pending: bool
    lead_forms: list[PageFormOption]
    lead_forms_hidden: int
    chosen_form: str = Field(
        description="The Meta form's external id; empty: a new form."
    )
    forms_synced_at: datetime | None
    source: str
    card: FormSummary
    advice: Recommendation | None
    ending_choice: EndingChoice | None
    ending: dict[str, Any] | None
    depth: FormDepthChoice | None


class AdvancedOut(Shape):
    campaign_card: CampaignTypeCard | None
    campaign_types: CampaignTypeChoices | None
    event_card: ConversionEventCard | None
    conversion_events: ConversionEventChoices | None
    pixels: list[PixelOption]
    buttons: ButtonChoices | None
    tracking: UrlTagsChoice | None
    cost_cap: CostCapChoice | None
    delivery: DeliveryChoices


class AdviceOut(Shape):
    audience: Recommendation | None
    placement: Recommendation


class ProposalOut(Shape):
    goal: str = Field(description="The saved goal key: `leads`, `messages`, `traffic`…")
    goal_label: str
    budget_label: str
    start_day: StartDay
    campaign_title: str
    campaign_named: bool
    name_max: int
    audience: AudienceOut
    interests: InterestsOut
    traits: TraitsOut
    variants: list[VariantCardOut]
    destination: DestinationOut
    lead_form: LeadFormOut | None
    advanced: AdvancedOut
    adjustments: list[dict[str, Any]]
    unconfirmed_names: list[str]
    regenerated: dict[str, bool] = Field(
        description="Per section (`audience`, `interests`, `traits`, `creative`, `form`): "
        "already written again — «Boshqacha qilib ko'r» is once per section."
    )
    advice: AdviceOut
    chat_questions: list[str]


class ReviewOut(Shape):
    """GET /launch/{id}/review, and every press on the review screen."""

    launch: LaunchHeadOut
    state: ReviewStateOut
    can_discard: bool
    proposal: ProposalOut | None = Field(
        description="Drawn once the proposal is ready."
    )
    writes_copy: bool | None = Field(
        None, description="Sent with the proposal: some advert still needs words."
    )


class ReviewRetryOut(ReviewOut):
    """POST /launch/{id}/retry: the review, and why the AI was not asked, if it was not."""

    refusal: str


class ReviewPollOut(Shape):
    """GET /launch/{id}/review/state: the cheap half, polled while work runs."""

    launch: LaunchHeadOut
    state: ReviewStateOut


__all__ = ["ReviewOut", "ReviewPollOut", "ReviewRetryOut"]
