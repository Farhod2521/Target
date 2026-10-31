"""The wizard's answers, key for key as ``packages/api/src/launch.ts`` reads them."""

from typing import Literal

from pydantic import Field

from app.common.contract import Camel, Money
from app.modules.ads.contract.launch.words import (
    LaunchErrorCode,
    LaunchGoal,
    LaunchMethod,
    LaunchStatus,
    PrepError,
    ResultKind,
    Step,
)

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
    google: dict[str, object] | None
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


__all__ = [
    "DraftPatch",
    "DraftStart",
    "GoalPress",
    "LaunchDraft",
]
