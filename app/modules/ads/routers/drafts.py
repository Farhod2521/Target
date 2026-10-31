"""«Reklama berish» as the cabinet asks for it: one draft across the steps.

The cabinet reads one draft (``/launch/drafts/{id}``) where this backend
keeps a launch read as three answers - its state, its plan and, past the
plan, its review. Every write answers with the whole draft read again. The
taps the screen has not sent yet (the plan's answers before «Davom etish»,
the tiles ticked, the offer typed) are kept beside the launch until they go.
"""

import time
import uuid
from typing import Any, Final

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.common.exceptions import DomainError, InputRefused
from app.modules.accounts.models import User
from app.modules.ads import refs
from app.modules.ads.constants import LaunchStatus
from app.modules.ads.contract.launch import taps as kept
from app.modules.ads.contract.launch.draft import (
    draft,
    flat_plan,
    flat_reading,
    plan_in,
    text_in,
)
from app.modules.ads.contract.launch.shapes import (
    DraftPatch,
    DraftStart,
    GoalPress,
    LaunchDraft,
)
from app.modules.ads.contract.launch.words import (
    goal_key,
    goal_keys,
    goal_of,
    method_of,
    status_of,
)
from app.modules.ads.models import Campaign, CampaignLaunch
from app.modules.ads.routers import launch as plan_routes
from app.modules.ads.routers import launch_media as media_routes
from app.modules.ads.routers import launch_review as review_routes
from app.modules.ads.routers.drafts_google import (
    google_of,
    patch_google,
    read_google,
    start_google,
)
from app.modules.ads.routers.launch import GoalReadingIn
from app.modules.ads.routers.launch_common import encoded, launch_head, owned_launch
from app.modules.ads.selectors.variants import launch_variants

router = APIRouter(prefix="/launch/drafts", tags=["launch"])

# A plan refusal's fields, as the plan screen names them.
PLAN_FIELDS: Final[dict[str, str]] = {
    "daily_budget": "dailyBudget",
    "goal_text": "goalWords",
    "link_url": "linkUrl",
    "phone_number": "phone",
    "chat_channel": "chatChannel",
    "welcome_text": "welcomeText",
    "chat_questions": "chatQuestions",
    "start_day": "start",
}
# The goal reading is asked and then read until written: so long, so often.
READING = {"poll_seconds": 1.0, "tries": 8}
WORKING: Final = frozenset({"building", "creating"})
# The patch's fields that are the screen's own, kept until they are sent.
KEPT: Final = ("media_source", "media", "method", "text_mode", "offer", "offers")


def renamed(refusal: InputRefused, names: dict[str, str]) -> InputRefused:
    """A refusal with its fields under the form's names."""
    problems = {names.get(key, key): value for key, value in refusal.problems.items()}
    return InputRefused(problems, refusal.message, hints=refusal.hints)


def launch_of(db: Session, *, user: User, draft_id: uuid.UUID) -> CampaignLaunch:
    return owned_launch(db, user=user, launch_id=draft_id)


def tapped_goal(taps: dict[str, Any]) -> str:
    """The goal tapped on the plan and not saved yet, by the backend's key."""
    mine = taps.get("plan") or {}
    goal = mine.get("goal")
    method = mine["method"] if "method" in mine else taps.get("method")
    return goal_key(goal, method, taps.get("offered") or []) if goal else ""


def read_plan(
    db: Session,
    *,
    user: User,
    launch: CampaignLaunch,
    taps: dict[str, Any],
    reuse: bool,
) -> dict[str, Any]:
    """``GET /plan`` for the goal tapped here (not yet sent): its fields, floor and presets."""
    key = tapped_goal(taps)
    if reuse:
        found = kept.kept_plan(launch.id, key)
        if isinstance(found, dict):
            return found

    def plain() -> dict[str, Any]:
        return flat_plan(plan_routes.plan(launch.id, db, user, goal=""))

    if key:
        # A key the plan does not take still answers the saved plan; the tap shows over it.
        try:
            plan = flat_plan(plan_routes.plan(launch.id, db, user, goal=key))
        except (DomainError, HTTPException, ValueError):
            db.rollback()
            plan = plain()
    else:
        plan = plain()
    offered = goal_keys(plan)
    if offered:
        taps["offered"] = offered
    kept.keep_plan(launch.id, key, plan)
    return plan


def _extras(db: Session, *, launch: CampaignLaunch) -> dict[str, Any]:
    """What only the launch knows: its campaign, whether it is the first, its texts."""
    answers = launch.answers or {}
    campaign_ref = refs.first_id(launch.created_refs or {}, "campaign")
    campaign_id = (
        db.scalar(
            select(Campaign.id).where(
                Campaign.owner_id == launch.owner_id,
                Campaign.external_id == campaign_ref,
            )
        )
        if campaign_ref
        else None
    )
    first = launch.status == LaunchStatus.CREATED and not db.scalar(
        select(func.count())
        .select_from(CampaignLaunch)
        .where(
            CampaignLaunch.owner_id == launch.owner_id,
            CampaignLaunch.status == LaunchStatus.CREATED,
            CampaignLaunch.id != launch.id,
            CampaignLaunch.created_at < launch.created_at,
        )
    )
    briefs = {
        str(variant.media_asset_id): variant.brief
        for variant in launch_variants(db, launch=launch)
        if variant.media_asset_id and variant.brief
    }
    return {
        "id": str(launch.id),
        "campaign_id": str(campaign_id) if campaign_id else None,
        "first_launch": first,
        "text": {
            "mode": answers.get("text_mode") or "",
            "shared": str(
                answers.get("shared_text", answers.get("offer_text", "")) or ""
            ),
            "asset_briefs": briefs,
        },
    }


def read_draft(db: Session, *, user: User, launch: CampaignLaunch) -> LaunchDraft:
    taps = kept.read(launch.id)
    head = encoded(launch_head(launch))
    # Polled every 2 s while working: the plan read a moment ago will do.
    plan = read_plan(
        db, user=user, launch=launch, taps=taps, reuse=bool(taps.get("working"))
    )
    early = status_of(head.get("status"))
    review: dict[str, Any] | None = None
    if early in WORKING:
        # The cheap half; the poll's count and the stage shown go back, so the
        # backend stops a runaway poll and says when the headline moved on.
        review = review_routes.review_poll(
            launch.id,
            db,
            user,
            tries=kept.tries(taps, "review"),
            shown=str(taps.get("shown") or ""),
        )
        kept.counted(taps, "review", review["state"]["tries"])
        token = ((review["state"].get("preparing") or {}).get("token")) or ""
        if token:
            taps["shown"] = token
    elif early != "draft":
        review = review_routes.review(launch.id, db, user, shown="")
    taps["working"] = early in WORKING
    kept.write(launch.id, taps)
    found = draft(
        head=head,
        plan=plan,
        review=review,
        taps=taps,
        extras=_extras(db, launch=launch),
        today=utcnow().date(),
    )
    return LaunchDraft.model_validate(found)


@router.post("", response_model=LaunchDraft)
def start(body: DraftStart, db: Db, user: CurrentUser) -> LaunchDraft:
    """Open a draft, or carry on the preparation already open."""
    if body.flow == "google":
        return start_google(db, user)
    opened = plan_routes.start(db, user)
    launch = launch_of(db, user=user, draft_id=uuid.UUID(opened["id"]))
    return read_draft(db, user=user, launch=launch)


@router.get("/{draft_id}", response_model=LaunchDraft)
def read(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> LaunchDraft:
    google = google_of(db, user=user, draft_id=draft_id)
    if google is not None:
        return read_google(db, google)
    return read_draft(db, user=user, launch=launch_of(db, user=user, draft_id=draft_id))


def text_taps(launch: CampaignLaunch, taps: dict[str, Any]) -> dict[str, Any]:
    """The texts as the screen shows them: a part it did not touch keeps what is saved."""
    answers = launch.answers or {}
    saved = {
        "text_mode": "each" if answers.get("text_mode") == "each" else "one",
        "offer": str(answers.get("shared_text", answers.get("offer_text", "")) or ""),
    }
    return saved | taps


@router.patch("/{draft_id}", response_model=LaunchDraft)
def patch(
    draft_id: uuid.UUID, body: DraftPatch, db: Db, user: CurrentUser
) -> LaunchDraft:
    """A tap. The plan's answers wait here until «Davom etish» (the patch with
    ``step``) sends them together: the plan takes every answer at once."""
    google = google_of(db, user=user, draft_id=draft_id)
    if google is not None:
        return patch_google(db, user=user, launch=google, body=body)
    launch = launch_of(db, user=user, draft_id=draft_id)
    sent = body.model_fields_set
    taps = kept.read(launch.id)
    for field in KEPT:
        value = getattr(body, field)
        # A method may be taken back (null); the rest only ever change.
        if field in sent and (value is not None or field == "method"):
            taps[field] = value
    answers = {
        field: value.model_dump(by_alias=False)
        if hasattr(value, "model_dump")
        else value
        for field in kept.PLAN_KEYS
        if field in sent
        for value in [getattr(body, field)]
    }
    if answers:
        taps["plan"] = {**(taps.get("plan") or {}), **answers}
    kept.write(launch.id, taps)
    if body.step and taps.get("plan"):
        plan = read_plan(db, user=user, launch=launch, taps=taps, reuse=False)
        try:
            plan_routes.save_plan(
                launch.id, plan_in(plan, taps["plan"], taps.get("method")), db, user
            )
        except InputRefused as refusal:
            raise renamed(refusal, PLAN_FIELDS) from refusal
        taps.pop("plan", None)
    if body.step:
        taps["step"] = body.step
    kept.write(launch.id, taps)
    if sent & {"text_mode", "offer", "offers"}:
        media_routes.media_text(launch.id, text_in(text_taps(launch, taps)), db, user)
    db.refresh(launch)
    return read_draft(db, user=user, launch=launch)


def _settled(found: dict[str, Any]) -> bool:
    if found.get("keep_polling") is not None:
        return not found["keep_polling"]
    return str(found.get("state") or "").lower() not in (
        "pending",
        "reading",
        "running",
    )


@router.post("/{draft_id}/goal-reading", response_model=LaunchDraft)
def read_goal(
    draft_id: uuid.UUID, body: GoalPress, db: Db, user: CurrentUser
) -> LaunchDraft:
    """The words, a ready phrase or a pick; the AI's reading is waited for here."""
    launch = launch_of(db, user=user, draft_id=draft_id)
    taps = kept.read(launch.id)
    plan = read_plan(db, user=user, launch=launch, taps=taps, reuse=False)
    offered = goal_keys(plan)

    def key(goal: str) -> str:
        return goal_key(goal, taps.get("method"), offered)

    if body.phrase:
        press = GoalReadingIn(phrase=key(body.phrase))
    elif body.pick:
        press = GoalReadingIn(pick=key(body.pick), goal_text=body.text or "")
    else:
        press = GoalReadingIn(goal_text=body.text or "")
    try:
        found = flat_reading(plan_routes.read_goal(launch.id, press, db, user))
    except InputRefused as refusal:
        raise renamed(refusal, {"goal_text": "text"}) from refusal
    for attempt in range(int(READING["tries"])):
        if _settled(found):
            break
        time.sleep(float(READING["poll_seconds"]))
        found = flat_reading(
            plan_routes.goal_reading(
                launch.id, db, user, tries=found.get("tries") or attempt + 1
            )
        )
    taps["reading"] = {
        key_: value for key_, value in found.items() if key_ != "keep_polling"
    }
    # A settled reading is the goal tapped: it shows, and goes with «Davom etish».
    goal = (
        goal_of(found.get("goal"))
        if str(found.get("state") or "").lower() == "found"
        else None
    )
    if goal:
        method = (
            (
                "website"
                if method_of(found.get("goal")) == "website"
                else taps.get("method") or "instant_form"
            )
            if goal == "lead"
            else None
        )
        mine = {**(taps.get("plan") or {}), "goal": goal, "method": method}
        if body.text is not None:
            mine["goal_words"] = body.text
        taps["plan"] = mine
        if method:
            taps["method"] = method
    kept.write(launch.id, taps)
    db.refresh(launch)
    return read_draft(db, user=user, launch=launch)


__all__ = [
    "launch_of",
    "read_draft",
    "renamed",
    "router",
    "tapped_goal",
    "text_taps",
]
