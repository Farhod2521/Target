"""The new-advert wizard, first step: open a preparation and answer the plan.

``POST /launch`` opens one. ``GET /launch/{id}`` says where it stands and
which screen to resume on (``plan``, ``media`` or ``review``). The plan is
read with ``GET /plan`` and saved with ``POST /plan``; saving moves the
wizard on to the pictures.

The first question can be answered in words. ``POST /plan/goal`` hands the
words (or a ready phrase, or a pick) over; when a reading was asked for,
poll ``GET /plan/goal?tries=n`` while ``keep_polling`` holds.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    CHAT_QUESTION_POLL_MS,
    GOAL_BY_PHRASE,
    GOAL_BY_PICK,
    GOAL_TEXT_MAX,
    GOAL_TEXT_MIN,
    MAX_CHAT_QUESTION_POLLS,
    MAX_GOAL_POLLS,
    READING_V3,
)
from app.modules.ads.inputs.plan import (
    CHAT_GOAL,
    FORM_GOAL,
    SAY_WHAT_YOU_NEED,
    PlanIn,
    check_plan,
    plan_frame,
    plan_goals,
    plan_initial,
    presets_for,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers.launch_common import (
    attempted,
    committed,
    encoded,
    launch_head,
    owned_launch,
    writable_launch,
)
from app.modules.ads.selectors.campaign_type import picker_v2_on
from app.modules.ads.selectors.goal_intent import goal_picker
from app.modules.ads.selectors.goals import goal_needs_form, goal_needs_pixel
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.lead_form import form_choice
from app.modules.ads.selectors.pixel import launch_conversion_source
from app.modules.ads.selectors.plan_picker import row_picker
from app.modules.ads.selectors.quality import catalogue_questions, chat_question_reading
from app.modules.ads.services import launch as launch_services
from app.modules.ads.services import readings
from app.modules.businesses.selectors import business_for_page
from app.modules.integrations.selectors.connection import instagram_permission_missing
from core.targeting import MAX_CHAT_QUESTIONS
from core.targeting.compat import default_offer, offer

router = APIRouter(prefix="/launch", tags=["launch"])
TRIES_Q = Query(0, ge=0, description="The last answer's `tries`.")


class GoalReadingIn(BaseModel):
    goal_text: str = Field("", max_length=GOAL_TEXT_MAX)
    phrase: str = Field("", description="A ready phrase's goal (or row) key.")
    pick: str = Field("", description="A goal (or row) picked from the list.")


@router.post("", status_code=status.HTTP_201_CREATED)
def start(db: Db, user: CurrentUser) -> dict[str, Any]:
    """Open a preparation - or carry on the one already open."""
    launch = committed(db, lambda: launch_services.start_launch(db, user=user))
    return launch_head(launch)


@router.get("/{launch_id}")
def launch_state(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    return launch_head(owned_launch(db, user=user, launch_id=launch_id))


def _extras(db: Session, *, launch: CampaignLaunch, goal: str) -> dict[str, Any]:
    """What the step draws beside the form, for the goal now selected."""
    page = launch_page(db, launch=launch)
    extras: dict[str, Any] = {
        "has_instagram": page is not None and page.has_instagram,
        "instagram_username": page.instagram_username
        if page is not None and page.can_open_profile
        else "",
        "ig_needs_permission": instagram_permission_missing(db, owner=launch.owner),
        "needs_pixel": goal_needs_pixel(db, launch=launch, goal=goal),
        "needs_form": goal_needs_form(db, launch=launch, goal=goal),
    }
    if extras["needs_pixel"]:
        extras["pixel"] = launch_conversion_source(db, launch=launch)
    if extras["needs_form"]:
        extras["form_choice"] = form_choice(db, launch=launch)
    return extras


def _plan(
    db: Session, *, launch: CampaignLaunch, user: User, goal: str, now: datetime
) -> dict[str, Any]:
    business = business_for_page(db, owner=user, page=launch.page)
    v2 = picker_v2_on(user=user)
    frame = plan_frame(db, launch=launch, user=user, goal=goal, now=now)
    answer: dict[str, Any] = {
        "launch": launch_head(launch),
        "picker_v2": v2,
        "goals": plan_goals(db, launch=launch, user=user),
        "frame": frame,
        "budget_presets": presets_for(frame),
        "initial": plan_initial(db, launch=launch, frame=frame, business=business),
    }
    if v2:
        chat = plan_frame(db, launch=launch, user=user, goal=CHAT_GOAL, now=now)
        answer |= {
            "picker": row_picker(db, launch=launch, now=now),
            "chat_channels": chat.channels,
            "chat_defaults": catalogue_questions(db, launch=launch, goal=CHAT_GOAL),
            "max_chat_questions": MAX_CHAT_QUESTIONS,
            **_extras(db, launch=launch, goal=FORM_GOAL),
            "pixel": launch_conversion_source(db, launch=launch),
        }
    else:
        answer |= {
            "picker": goal_picker(db, launch=launch, now=now),
            **_extras(db, launch=launch, goal=goal),
        }
    return encoded(answer)


@router.get("/{launch_id}/plan")
def plan(
    launch_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    goal: str = Query("", description="Draw the fields for this goal instead."),
) -> dict[str, Any]:
    """The plan step: goals, the budget's floor, where the tap goes, the day."""
    launch = owned_launch(db, user=user, launch_id=launch_id)
    chosen = goal or str(launch.answers.get("goal") or "")
    return _plan(db, launch=launch, user=user, goal=chosen, now=utcnow())


@router.post("/{launch_id}/plan")
def save_plan(
    launch_id: uuid.UUID, body: PlanIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Every answer the first screen carries, saved together."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    answers = check_plan(db, launch=launch, user=user, body=body, now=utcnow())
    committed(db, lambda: launch_services.save_answers(db, launch=launch, **answers))
    return launch_head(launch) | {"next": "media"}


def _reading(
    db: Session,
    *,
    launch: CampaignLaunch,
    user: User,
    tries: int,
    error: str = "",
) -> dict[str, Any]:
    now = utcnow()
    gave_up = tries >= MAX_GOAL_POLLS
    if picker_v2_on(user=user):
        picker = row_picker(db, launch=launch, now=now, gave_up=gave_up)
        reading = picker["reading"]
    else:
        picker = goal_picker(db, launch=launch, now=now, gave_up=gave_up)
        reading = picker.get("reading")
    state = str(getattr(reading, "state", "") or "")
    return encoded(
        {
            "reading": reading,
            "picker": picker,
            "error": error,
            "tries": tries,
            "keep_polling": state == "pending" and not gave_up,
        }
    )


@router.get("/{launch_id}/plan/goal")
def goal_reading(
    launch_id: uuid.UUID, db: Db, user: CurrentUser, tries: int = TRIES_Q
) -> dict[str, Any]:
    launch = owned_launch(db, user=user, launch_id=launch_id)
    return _reading(db, launch=launch, user=user, tries=tries + 1)


@router.post("/{launch_id}/plan/goal")
def read_goal(
    launch_id: uuid.UUID, body: GoalReadingIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """One of three presses: the words, a ready phrase, or a pick."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    v2 = picker_v2_on(user=user)
    now = utcnow()
    if v2:
        picker = row_picker(db, launch=launch, now=now)
        phrases = dict(picker["goal_phrases"])
        keys = set(picker["picker_table"]["rows"]) | set(
            picker["picker_table"]["goals"]
        )
        allowed_phrases = keys
    else:
        picker = goal_picker(db, launch=launch, now=now)
        phrases = {item.goal: item.phrase for item in picker["goal_phrases"]}
        keys = {option.goal for option in picker["goal_options"]}
        allowed_phrases = set(phrases)
    if body.phrase and body.phrase not in allowed_phrases:
        raise InputRefused({"phrase": "Ro'yxatdan tanlang."})
    if body.pick and body.pick not in keys:
        raise InputRefused({"pick": "Ro'yxatdan tanlang."})
    if not (body.phrase or body.pick) and len(body.goal_text) < GOAL_TEXT_MIN:
        raise InputRefused({"goal_text": SAY_WHAT_YOU_NEED})

    def run() -> None:
        if v2:
            _settle_row(db, launch=launch, body=body, phrases=phrases, now=now)
        elif body.phrase:
            readings.choose_goal(
                db,
                launch=launch,
                goal=body.phrase,
                by=GOAL_BY_PHRASE,
                text=phrases[body.phrase],
            )
        elif body.pick:
            readings.choose_goal(
                db, launch=launch, goal=body.pick, by=GOAL_BY_PICK, text=body.goal_text
            )
        else:
            readings.request_goal_reading(
                db, launch=launch, text=body.goal_text, now=now
            )

    error = attempted(db, run)
    return _reading(db, launch=launch, user=user, tries=0, error=error)


def _settle_row(
    db: Session,
    *,
    launch: CampaignLaunch,
    body: GoalReadingIn,
    phrases: dict[str, str],
    now: datetime,
) -> None:
    if body.phrase:
        said = phrases.get(body.phrase) or phrases.get(_row_of(launch, body.phrase), "")
        readings.choose_row(
            db, launch=launch, key=body.phrase, by=GOAL_BY_PHRASE, text=said
        )
    elif body.pick:
        readings.choose_row(
            db, launch=launch, key=body.pick, by=GOAL_BY_PICK, text=body.goal_text
        )
    else:
        readings.request_goal_reading(
            db, launch=launch, text=body.goal_text, now=now, version=READING_V3
        )


def _row_of(launch: CampaignLaunch, key: str) -> str:
    """A goal key's default row; a row key as it is."""
    if offer(provider=launch.provider, key=key) is not None:
        return key
    found = default_offer(provider=launch.provider, goal=key)
    return found.key if found is not None else ""


def _chat_questions(
    launch: CampaignLaunch, *, tries: int, error: str = ""
) -> dict[str, Any]:
    reading = chat_question_reading(launch=launch)
    gave_up = tries >= MAX_CHAT_QUESTION_POLLS
    return encoded(
        {
            "reading": reading,
            "tries": tries,
            "gave_up": gave_up,
            "poll_ms": CHAT_QUESTION_POLL_MS,
            "error": error,
            "keep_polling": str(reading.get("state", "")) == "pending" and not gave_up,
        }
    )


@router.get("/{launch_id}/plan/chat-questions")
def chat_questions(
    launch_id: uuid.UUID, db: Db, user: CurrentUser, tries: int = TRIES_Q
) -> dict[str, Any]:
    """The questions Claude is writing for a chat advert, as they stand."""
    launch = owned_launch(db, user=user, launch_id=launch_id)
    return _chat_questions(launch, tries=tries + 1)


@router.post("/{launch_id}/plan/chat-questions")
def ask_chat_questions(
    launch_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Ask Claude for the questions a chat advert offers under its greeting."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    error = attempted(
        db, lambda: readings.request_chat_questions(db, launch=launch, now=utcnow())
    )
    return _chat_questions(launch, tries=0, error=error)
