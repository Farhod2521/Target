"""The wizard's answers, key for key as ``packages/api/src/launch.ts`` reads them."""

from typing import Literal

from pydantic import Field

from app.common.contract import Camel, Money
from app.modules.ads.constants import MAX_GEO_ADDRESS, MAX_GEO_PLACES
from app.modules.ads.contract.launch.words import (
    LaunchErrorCode,
    LaunchGoal,
    LaunchMethod,
    LaunchStatus,
    PrepError,
    ResultKind,
    Step,
)
from core.targeting import MAX_RADIUS_KM, MIN_RADIUS_KM

By = Literal["ai", "me"]
ChatChannel = Literal["messenger", "instagram"]
EditSection = Literal["aud", "geo", "int", "hab", "reach", "ads", "form", "adv"]
NoticeTarget = Literal[
    "aud",
    "geo",
    "int",
    "hab",
    "reach",
    "ads",
    "form",
    "adv",
    "plan",
    "media",
    "words",
    "billing",
    "budget_fit",
    "ads_trim",
    "profile",
    "connections",
]
FormField = Literal[
    "full_name",
    "first_name",
    "phone",
    "last_name",
    "email",
    "city",
    "region",
    "country",
    "zip",
    "address",
]


class GoalReading(Camel):
    state: Literal["found", "two", "sale", "unclear", "failed"]
    by: Literal["ai", "phrase", "pick"]
    goal: LaunchGoal | None
    quote: str
    options: list[LaunchGoal]


class EndingLine(Camel):
    words: str
    target: str


class LeadFormChoice(Camel):
    by: By
    depth: Literal["short", "deep"]
    form_id: str | None
    name: str
    questions: list[str]
    ending: EndingLine | None
    missing: bool


class NoticeAction(Camel):
    label: str
    to: NoticeTarget
    style: Literal["button", "link"]


class ProposalNotice(Camel):
    id: str
    icon: Literal["users", "ai", "lead", "card", "wallet", "film", "link", "search"]
    tone: Literal["w", "a", "d"]
    title: str
    text: str
    action: NoticeAction | None = None


class Reach(Camel):
    min: int
    max: int
    level: Literal["narrow", "good", "wide"]
    from_: int = Field(
        alias="from", description="Where the estimate starts, % of the track."
    )
    width: int


class ProposalAd(Camel):
    id: str
    tone: int = Field(description="A placeholder tile's gradient, 1-6.")
    art: str
    headline: str
    text: str
    thumb: str | None = None
    video: bool | None = None


class GoalForm(Camel):
    name: str
    questions: int


class GoalChat(Camel):
    channel: ChatChannel
    questions: int


class ProposalGoal(Camel):
    kind: ResultKind
    by: By
    method: LaunchMethod | None = None
    form: GoalForm | None = None
    site: str | None = None
    search: bool | None = None
    dest: str | None = None
    chat: GoalChat | None = None


class ProposalAudience(Camel):
    by: By
    places: list[str]
    age: list[int] | None
    genders: Literal["all", "m", "f"]
    placements: str | None = None
    interests: list[str] | None = None
    keywords: int | None = None
    minus: int | None = None
    reach: Reach | None = None


class ProposalBudget(Camel):
    by: By
    ends_at: str | None
    total: Money | None
    starts_at: str
    fixed_currency: bool | None = None


class Proposal(Camel):
    say: str
    name: str
    goal: ProposalGoal
    audience: ProposalAudience
    budget: ProposalBudget
    changes: list[dict[str, object]]
    ads: list[ProposalAd]
    attention: list[ProposalNotice]
    blockers: list[ProposalNotice]


class Finding(Camel):
    label: str
    value: str
    tentative: bool | None = None


class Building(Camel):
    findings: list[Finding]
    audience: bool
    texts_done: int
    texts_total: int


class Creation(Camel):
    stage: Literal[0, 1, 2, 3]
    campaign: bool
    adset: bool
    ads_done: int
    ads_total: int
    sent_at: str | None


class Guide(Camel):
    cause: str
    steps: list[str]


class FailureFix(Camel):
    label: str
    to: NoticeTarget
    href: str | None = None


class Made(Camel):
    campaign: bool
    adset: bool
    ads_done: int
    ads_total: int


class Failure(Camel):
    code: LaunchErrorCode
    say: str
    title: str
    text: str
    explain: str
    hint: str
    guide: Guide
    fix: FailureFix
    raw: str | None = None
    made: Made
    explanation_html: str | None = Field(
        None, description="Why the network refused it and what to do, as HTML."
    )
    explaining: bool | None = Field(
        None, description="That answer is being written: read the draft again."
    )


class DraftPage(Camel):
    has_instagram: bool
    pixel: str | None
    region: str


class GoalPhrase(Camel):
    goal: LaunchGoal
    phrase: str


class Delivery(Camel):
    reason: str


class GoogleKeyword(Camel):
    text: str
    volume: int


class UrlCheck(Camel):
    ok: bool
    seconds: float


class GoogleWords(Camel):
    say: str
    keywords: list[GoogleKeyword]
    minus: list[str]
    headlines: list[str]
    descriptions: list[str]
    url: str
    url_check: UrlCheck | None
    paths: list[str]
    places: list[str]


class Area(Camel):
    key: str
    name: str
    parent: str | None = None


class LaunchDraft(Camel):
    id: str
    flow: Literal["campaigns", "google"]
    network_id: str
    status: LaunchStatus
    step: Step
    goal_mode: Literal["list", "words"]
    goal_words: str
    goal: LaunchGoal | None
    ai_goal: LaunchGoal | None
    offered_goals: list[LaunchGoal] | None = None
    method: LaunchMethod | None
    daily_budget: Money
    min_budget: Money
    budget_presets: list[Money]
    start: Literal["today", "tomorrow"]
    media_source: Literal["ig", "lib"]
    media: list[str]
    text_mode: Literal["one", "each"]
    offer: str
    offers: dict[str, str]
    building: Building | None
    proposal: Proposal | None
    creation: Creation | None
    failure: Failure | None
    first_launch: bool
    campaign_id: str | None
    review_eta: Literal["hour", "hours"]
    google: GoogleWords | None
    link_url: str
    phone: str
    chat_channel: ChatChannel
    welcome_text: str
    chat_questions: list[str]
    lead_form: LeadFormChoice | None
    areas: list[str]
    page: DraftPage
    reading: GoalReading | None
    goal_phrases: list[GoalPhrase]
    prep_error: PrepError | None
    delivery: Delivery | None
    created_ad_id: str | None
    regenerated: list[EditSection]


class DraftStart(Camel):
    flow: Literal["campaigns", "google"] = "campaigns"
    resume: str | None = None


class DraftPatch(Camel):
    """A tap on one of the steps. ``step`` («Davom etish») sends the plan's answers."""

    step: Step | None = None
    goal_mode: Literal["list", "words"] | None = None
    goal_words: str | None = None
    goal: LaunchGoal | None = None
    method: LaunchMethod | None = None
    daily_budget: Money | None = None
    start: Literal["today", "tomorrow"] | None = None
    media_source: Literal["ig", "lib"] | None = None
    media: list[str] | None = None
    text_mode: Literal["one", "each"] | None = None
    offer: str | None = None
    offers: dict[str, str] | None = None
    link_url: str | None = None
    phone: str | None = None
    chat_channel: ChatChannel | None = None
    welcome_text: str | None = None
    chat_questions: list[str] | None = None
    areas: list[str] | None = None


class GoalPress(Camel):
    """One of three presses under the words: the words, a ready phrase, or a pick."""

    text: str | None = None
    phrase: LaunchGoal | None = None
    pick: LaunchGoal | None = None


ListMode = Literal["include", "exclude", "off"]


class AudienceList(Camel):
    id: str
    name: str
    sub: str
    mode: ListMode


class EditAudience(Camel):
    who: Literal["auto", "interests", "broad"]
    apps: Literal["auto", "fbig"]
    optimize: Literal["all", "quality"]
    age: list[int]
    ai_age: list[int]
    genders: list[Literal["m", "f"]]
    lists: list[AudienceList]


class Place(Camel):
    id: str
    name: str
    type: Literal["city", "region", "country"]


class PlaceFound(Place):
    """A row of the place search; ``context`` tells two Tashkents apart."""

    context: str
    country_code: str


class EditGeo(Camel):
    mode: Literal["list", "map"]
    places: list[Place]
    km: float
    address: str = Field("", max_length=MAX_GEO_ADDRESS)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    min_km: int = MIN_RADIUS_KM
    max_km: int = MAX_RADIUS_KM
    place_limit: int = MAX_GEO_PLACES


class AdCheck(Camel):
    id: str
    level: Literal["danger", "info"]
    title: str
    text: str
    fix: Literal["remove_phone", "rewrite"]


class EditAd(Camel):
    id: str
    tone: int
    art: str
    name: str
    text: str
    headline: str
    desc: str
    by: By
    instagram: bool
    checks: list[AdCheck]
    thumb: str | None = None
    video: bool | None = None


class ExistingForm(Camel):
    id: str
    name: str
    leads: int
    questions: int
    date: str
    archived: bool


class FormQuestion(Camel):
    id: str
    text: str
    options: list[str]


class LeadFormEdit(Camel):
    existing: list[ExistingForm]
    choice: str
    name: str
    depth: Literal["short", "deep"] | None = None
    fields: dict[FormField, bool]
    questions: list[FormQuestion]
    end: Literal["none", "site", "telegram", "call"]
    end_target: str
    end_button: str
    end_title: str
    end_text: str
    privacy: str


class AdvRow(Camel):
    key: str
    en: str = Field(description="The network's own name for the setting.")
    value: str
    mode: Literal["ro", "me", "", "sw"]
    options: list[str]
    on: bool | None = None


class ProposalEdit(Camel):
    say: dict[EditSection, str]
    aud: EditAudience
    geo: EditGeo
    interests: list[str]
    habits: list[str]
    ads: list[EditAd]
    form: LeadFormEdit
    adv: list[AdvRow]


class FormVariant(Camel):
    """The questions the AI writes for one form depth; pending until written."""

    state: Literal["pending", "ready", "failed"]
    questions: list[FormQuestion]


class NameIn(Camel):
    name: str = ""


class FormEnding(Camel):
    kind: Literal["none", "website", "telegram", "call"]
    website: str
    telegram: str
    phone: str
    button: str
    title: str
    body: str


class PageForm(Camel):
    id: str
    name: str
    questions: list[str]
    typed_contacts: list[str] = Field(
        description="Contact questions asked as free text: the network refuses such a form."
    )
    ending: EndingLine | None
    leads: int | None
    created: str | None


class TypedQuestion(Camel):
    label: str
    options: list[str]


class StandardQuestion(Camel):
    kind: FormField
    checked: bool


class LeadFormPanel(Camel):
    forms: list[PageForm]
    chosen: str = Field(description="The chosen form's id; empty builds a new one.")
    name: str
    standard: list[StandardQuestion]
    typed: list[TypedQuestion]
    ending: FormEnding
    synced_at: str | None
    max_questions: int
    max_options: int


class LeadFormSave(Camel):
    form_id: str
    name: str
    kinds: list[FormField]
    typed: list[TypedQuestion]
    ending: FormEnding


class DepthIn(Camel):
    depth: Literal["short", "deep"] = "short"


class ChatQuestionReading(Camel):
    state: Literal["idle", "pending", "done", "failed"]
    questions: list[str]


class MediaAsset(Camel):
    id: str
    tone: int
    art: str
    caption: str
    video: str | None = Field(
        None, description='"0:31", or "" when unknown; absent for pictures.'
    )
    post: bool | None = None
    blocked: bool | None = Field(None, description="Instagram refuses to advertise it.")
    small: bool | None = None
    permalink: str | None = None
    state: (
        Literal["ready", "uploading", "upload_failed", "deleting", "delete_failed"]
        | None
    ) = None
    progress: float | None = None
    size_mb: int | None = None
    text: str | None = None
    date: str | None = None
    used_in: int | None = Field(
        None, description="Running adverts using it: it cannot be deleted."
    )
    thumb: str | None = None
    error: str | None = None


class InstagramProfile(Camel):
    handle: str
    initials: str
    sub: str
    posts: int
    followers: int
    following: int


class MediaLibrary(Camel):
    say: str
    instagram: InstagramProfile | None
    page_name: str
    currency: str
    posts: list[MediaAsset]
    library: list[MediaAsset]
    synced_at: str | None
    held: dict[str, int] = Field(
        description="Tiles already in the launch, by id: their position."
    )
    uploads: list[MediaAsset] = Field(
        description="Uploads the network has not taken in yet."
    )
    max_image_mb: int | None = None
    max_video_mb: int | None = None
    accept: str | None = None


class UploadDone(Camel):
    upload_id: str
    total: int
    name: str


__all__ = [
    "Area",
    "ChatQuestionReading",
    "DepthIn",
    "DraftPatch",
    "DraftStart",
    "ExistingForm",
    "FormVariant",
    "GoalPress",
    "GoogleWords",
    "LaunchDraft",
    "LeadFormPanel",
    "LeadFormSave",
    "MediaAsset",
    "MediaLibrary",
    "NameIn",
    "ProposalEdit",
    "UploadDone",
]
