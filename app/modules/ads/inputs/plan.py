"""The first step: what is wanted, how much a day, where the tap goes, when.

Two pickers share one body. The old one names a goal; the three-question
one names a row (``campaign_type``) or an outcome, and every destination
field is sent but only the ones the row asks for are kept.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.common.money import provider_money, to_major
from app.common.presets import goal_label, offered_goals
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    CAMPAIGN_TYPE,
    CHAT_QUESTIONS,
    CLOSED_REASONS,
    GOAL_TEXT_MAX,
    START_TODAY,
    START_TOMORROW,
)
from app.modules.ads.inputs import Problems
from app.modules.ads.inputs.budget import budget_minor, budget_presets
from app.modules.ads.inputs.destination import own_site, phone_in
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.campaign_type import (
    campaign_type_locked,
    effective_campaign_type,
    picker_v2_on,
)
from app.modules.ads.selectors.copy_notes import destination_phone
from app.modules.ads.selectors.goal_intent import words_for_goal
from app.modules.ads.selectors.goals import (
    chat_channels,
    goal_needs_link,
    goal_needs_phone,
    goal_opens_chat,
    goal_optimization,
    legacy_plan_goals,
    opening_channel,
)
from app.modules.ads.selectors.launches import last_daily_budget
from app.modules.ads.selectors.plan_picker import account_facts, words_for_row
from app.modules.ads.selectors.schedule import offered_days
from app.modules.ads.services.readings import visible_rows
from app.modules.ads.services.targeting import minimum_budget, welcome_greeting
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import business_for_page
from core.targeting import MAX_CHAT_QUESTIONS, MAX_GREETING_CHARS, clean_questions
from core.targeting.compat import (
    Offer,
    closed_by,
    default_offer,
    outcome_default,
    outcome_spec,
)

SAY_WHAT_YOU_NEED = "Nima kerakligini yozing yoki ro'yxatdan tanlang."
QUESTION_CHARS = 80
ASKED_BY = {
    "link_url": "link",
    "phone_number": "phone",
    "chat_channel": "chat",
    "welcome_text": "chat",
    "chat_questions": "chat",
}


class PlanIn(BaseModel):
    goal: str = ""
    goal_mode: str = Field("", description="Which half of the first question sent it.")
    goal_text: str = Field("", max_length=GOAL_TEXT_MAX)
    outcome: str = Field("", max_length=32, description="Three-question picker only.")
    campaign_type: str = Field(
        "", max_length=64, description="Three-question picker only."
    )
    daily_budget: Decimal | None = Field(None, description="In whole currency units.")
    link_url: str = Field("", max_length=1000)
    phone_number: str = Field("", max_length=32)
    chat_channel: str = ""
    welcome_text: str = ""
    chat_questions: list[str] = Field(default_factory=list)
    start_day: Literal["today", "tomorrow"] = START_TODAY


@dataclass(frozen=True, slots=True)
class PlanFrame:
    """What the step offers for one goal: the floor, the fields, the days."""

    goal: str
    provider: str
    currency: str
    places: int
    min_daily_minor: int
    needs_link: bool
    opens_chat: bool
    needs_phone: bool
    region: str
    channels: tuple[str, ...]
    days: tuple[date, date]


def _goal_of(outcome: str) -> str:
    spec = outcome_spec(outcome)
    return spec.goals[0] if spec is not None else ""


CHAT_GOAL = _goal_of("messages")
FORM_GOAL = _goal_of("requests")


def plan_frame(
    db: Session, *, launch: CampaignLaunch, user: User, goal: str, now: datetime
) -> PlanFrame:
    business = business_for_page(db, owner=user, page=launch.page)
    money = provider_money(provider=launch.provider)
    optimization = goal_optimization(db, launch=launch, goal=goal)
    return PlanFrame(
        goal=goal,
        provider=launch.provider,
        currency=launch.currency,
        places=money.decimal_places(launch.currency),
        min_daily_minor=minimum_budget(
            ad_account=launch.ad_account, optimization_goal=optimization
        ),
        needs_link=goal_needs_link(db, launch=launch, goal=goal),
        opens_chat=goal_opens_chat(db, launch=launch, goal=goal),
        needs_phone=goal_needs_phone(db, launch=launch, goal=goal),
        region=business.country_code if business else "",
        channels=chat_channels(db, launch=launch, goal=goal),
        days=offered_days(launch=launch, now=now),
    )


def plan_initial(
    db: Session, *, launch: CampaignLaunch, frame: PlanFrame, business: Business | None
) -> dict[str, Any]:
    """What each box opens on, best answer first."""
    budget = launch.daily_budget_minor or last_daily_budget(db, launch=launch)
    return {
        "goal": frame.goal,
        "goal_text": launch.answers.get("goal_text") or "",
        "daily_budget": to_major(
            amount_minor=(budget or frame.min_daily_minor) or None, places=frame.places
        ),
        "link_url": launch.answers.get("link_url")
        or (business.website if business else ""),
        "welcome_text": welcome_greeting(db, launch=launch, business=business)
        if business is not None
        else "",
        "chat_channel": opening_channel(db, launch=launch, goal=frame.goal),
        "chat_questions": list(launch.answers.get(CHAT_QUESTIONS) or []),
        "start_day": START_TOMORROW
        if launch.start_date == frame.days[1]
        else START_TODAY,
        "phone_number": destination_phone(launch=launch, business=business)
        if business is not None
        else "",
        CAMPAIGN_TYPE: effective_campaign_type(launch=launch),
    }


def plan_goals(
    db: Session, *, launch: CampaignLaunch, user: User
) -> list[dict[str, str]]:
    business = business_for_page(db, owner=user, page=launch.page)
    category = business.category if business else ""
    found = (
        offered_goals(provider=launch.provider, category=category)
        if picker_v2_on(user=user)
        else legacy_plan_goals(provider=launch.provider, category=category)
    )
    return [
        {"goal": preset.goal, "label": str(goal_label(preset=preset))}
        for preset in found
    ]


def chosen_row(db: Session, *, launch: CampaignLaunch, body: PlanIn) -> Offer | None:
    """The row being submitted on the three-question picker."""
    held = effective_campaign_type(launch=launch)
    rows = {row.key: row for row in visible_rows(db, launch, keep=held)}
    if body.campaign_type in rows:
        return rows[body.campaign_type]
    if body.goal:
        stored = rows.get(str(launch.answers.get(CAMPAIGN_TYPE) or ""))
        if stored is not None and stored.goal == body.goal:
            return stored
        found = default_offer(provider=launch.provider, goal=body.goal)
    else:
        found = outcome_default(provider=launch.provider, outcome=body.outcome)
    return found if found is not None and found.key in rows else None


def check_plan(
    db: Session, *, launch: CampaignLaunch, user: User, body: PlanIn, now: datetime
) -> dict[str, Any]:
    """The answers ``save_answers`` takes, or :class:`InputRefused`."""
    if picker_v2_on(user=user):
        return _check_rows(db, launch=launch, user=user, body=body, now=now)
    problems = Problems()
    offered = {item["goal"] for item in plan_goals(db, launch=launch, user=user)}
    if body.goal not in offered:
        problems.add("goal", SAY_WHAT_YOU_NEED)
        problems.refuse()
    frame = plan_frame(db, launch=launch, user=user, goal=body.goal, now=now)
    answers = _destination(body, frame=frame, problems=problems)
    answers |= _money_and_day(body, frame=frame, problems=problems)
    problems.refuse()
    answers["chat_questions"] = None
    answers["goal"] = body.goal
    answers["goal_text"] = words_for_goal(
        launch=launch, goal=body.goal, words=body.goal_text, mode=body.goal_mode
    )
    return answers


def _check_rows(
    db: Session, *, launch: CampaignLaunch, user: User, body: PlanIn, now: datetime
) -> dict[str, Any]:
    problems = Problems()
    row = chosen_row(db, launch=launch, body=body)
    if row is None:
        problems.add("goal", SAY_WHAT_YOU_NEED)
        problems.refuse()
    assert row is not None
    closed = closed_by(row, account_facts(db, launch=launch))
    if closed:
        problems.add(CAMPAIGN_TYPE, CLOSED_REASONS.get(closed[0], ""))
    frame = plan_frame(db, launch=launch, user=user, goal=row.goal, now=now)
    floor = minimum_budget(
        ad_account=launch.ad_account, optimization_goal=row.kind.optimization_goal
    )
    frame = PlanFrame(**{**_fields(frame), "min_daily_minor": floor})
    asked = {
        "link": frame.needs_link,
        "phone": frame.needs_phone,
        "chat": frame.opens_chat,
    }
    chat_frame = plan_frame(db, launch=launch, user=user, goal=CHAT_GOAL, now=now)
    answers = _destination(
        body,
        frame=PlanFrame(
            **{**_fields(frame), "channels": chat_frame.channels, "opens_chat": True}
        ),
        problems=problems,
        asked=asked,
    )
    answers |= _money_and_day(body, frame=frame, problems=problems)
    problems.refuse()
    answers["goal"] = row.goal
    answers["goal_text"] = words_for_row(
        launch=launch, row=row, words=body.goal_text, mode=body.goal_mode
    )
    if not campaign_type_locked(launch=launch):
        answers[CAMPAIGN_TYPE] = row.key
    return answers


def _fields(frame: PlanFrame) -> dict[str, Any]:
    return {name: getattr(frame, name) for name in PlanFrame.__slots__}


def _destination(
    body: PlanIn,
    *,
    frame: PlanFrame,
    problems: Problems,
    asked: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Each destination field the goal asks for, checked; ``None`` otherwise."""
    wanted = asked or {
        "link": frame.needs_link,
        "phone": frame.needs_phone,
        "chat": frame.opens_chat,
    }
    answers: dict[str, Any] = dict.fromkeys(ASKED_BY)
    if wanted["link"]:
        answers["link_url"] = own_site(
            body.link_url, problems=problems, field="link_url"
        )
    if wanted["phone"]:
        answers["phone_number"] = phone_in(
            body.phone_number,
            region=frame.region,
            problems=problems,
            field="phone_number",
        )
    if wanted["chat"]:
        answers |= _chat(body, frame=frame, problems=problems)
    return answers


def _chat(body: PlanIn, *, frame: PlanFrame, problems: Problems) -> dict[str, Any]:
    welcome = body.welcome_text.strip()
    if len(welcome) > MAX_GREETING_CHARS:
        problems.add(
            "welcome_text", f"Salom matni {MAX_GREETING_CHARS} belgidan oshmasin."
        )
    channel = body.chat_channel
    if frame.channels and channel not in frame.channels:
        if channel or len(frame.channels) > 1:
            problems.add("chat_channel", "Odamlar qayerga yozishini tanlang.")
        channel = ""
    questions = list(clean_questions(body.chat_questions))
    if len(questions) > MAX_CHAT_QUESTIONS:
        problems.add(
            "chat_questions",
            f"Ko'pi bilan {MAX_CHAT_QUESTIONS} ta savol qo'shish mumkin.",
        )
    elif any(len(question) > QUESTION_CHARS for question in questions):
        problems.add(
            "chat_questions", f"Har bir savol {QUESTION_CHARS} belgidan oshmasin."
        )
    elif questions and not welcome:
        problems.add(
            "chat_questions",
            "Savollar bilan birga «Suhbat qanday boshlansin?» ham yozing.",
        )
    return {
        "welcome_text": welcome,
        "chat_channel": channel or None,
        "chat_questions": questions,
    }


def _money_and_day(
    body: PlanIn, *, frame: PlanFrame, problems: Problems
) -> dict[str, Any]:
    money = provider_money(provider=frame.provider)
    minor = budget_minor(
        body.daily_budget,
        currency=frame.currency,
        money=money,
        floor_minor=frame.min_daily_minor,
        problems=problems,
    )
    today, tomorrow = frame.days
    start = tomorrow if body.start_day == START_TOMORROW else today
    return {"daily_budget_minor": minor, "start_date": start.isoformat()}


def presets_for(frame: PlanFrame) -> list[str]:
    return budget_presets(min_daily_minor=frame.min_daily_minor, places=frame.places)
