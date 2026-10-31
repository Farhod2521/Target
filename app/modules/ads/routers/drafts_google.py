"""The Google wizard behind the draft's own paths.

The cabinet asks one draft for either network; a draft id that is a Google
launch is answered here. Answers wait beside the launch until the patch that
moves on, then go together; the AI writes the words once for them.
"""

import uuid
from typing import Any, Final

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.contract import Money, zero_or
from app.common.db import utcnow
from app.common.exceptions import DomainError, InputRefused
from app.modules.accounts.models import User
from app.modules.ads.constants import LaunchStatus
from app.modules.ads.contract.launch import taps as kept
from app.modules.ads.contract.launch.google import (
    GOAL_KEYS,
    areas_of,
    chosen_areas,
    draft,
)
from app.modules.ads.contract.launch.shapes import (
    Area,
    DraftPatch,
    GoogleWords,
    LaunchDraft,
)
from app.modules.ads.contract.launch.words import whole_of
from app.modules.ads.models import GoogleLaunch
from app.modules.ads.routers import google as google_routes
from app.modules.ads.routers.google import AnswersIn, WordsIn, switched_on
from app.modules.ads.routers.launch_common import committed
from app.modules.ads.selectors.audiences_chosen import area_options
from app.modules.ads.selectors.google import google_launch_for, launch_profile
from app.modules.ads.services import google as google_services

router = APIRouter(prefix="/launch/drafts", tags=["launch: google"])

# A refusal that names no field, by the input the plan step draws it under.
ANSWER_CODES: Final[dict[str, str]] = {
    "google_website_required": "linkUrl",
    "google_phone_required": "phone",
    "google_budget_required": "budget",
    "google_places_too_many": "areas",
    "google_goal_unknown": "goal",
}
ANSWER_KEYS: Final = ("goal", "link_url", "phone", "areas", "daily_budget")


def google_of(db: Session, *, user: User, draft_id: uuid.UUID) -> GoogleLaunch | None:
    """The owner's Google launch under this id, if it is one."""
    found = google_launch_for(db, owner=user, launch_id=draft_id)
    if found is not None:
        switched_on(user)
    return found


def read_google(db: Session, launch: GoogleLaunch) -> LaunchDraft:
    profile = launch_profile(db, launch=launch)
    country = profile.country_code if profile else ""
    return LaunchDraft.model_validate(
        draft(
            launch,
            taps=kept.read(launch.id),
            options=area_options(db, country_code=country) if country else [],
            region=country,
            now=utcnow(),
        )
    )


def start_google(db: Session, user: User) -> LaunchDraft:
    switched_on(user)
    launch = committed(db, lambda: google_services.start_google_launch(db, user=user))
    return read_google(db, launch)


def _on_field(refusal: DomainError, field: str) -> InputRefused:
    """A refusal under the input it is about, keeping its own code."""
    named = InputRefused({field: refusal.message})
    named.code = refusal.code
    return named


def _send_answers(
    db: Session, *, user: User, launch: GoogleLaunch, pending: dict[str, Any]
) -> None:
    tapped = pending.get("daily_budget")
    budget = (
        Money.model_validate(tapped)
        if tapped
        else zero_or(
            launch.daily_budget_minor,
            launch.currency,
            provider=launch.ad_account.provider,
        )
    )
    body = AnswersIn(
        goal=GOAL_KEYS.get(pending["goal"] or "", "")
        if "goal" in pending
        else launch.goal,
        final_url=pending.get("link_url", launch.final_url),
        phone=pending.get("phone", launch.phone),
        areas=pending["areas"] if "areas" in pending else chosen_areas(launch),
        budget=str(whole_of(budget)),
    )
    try:
        google_routes.save_answers(launch.id, body, db, user)
    except DomainError as refusal:
        field = ANSWER_CODES.get(refusal.code)
        if field is None:
            raise
        raise _on_field(refusal, field) from refusal


def patch_google(
    db: Session, *, user: User, launch: GoogleLaunch, body: DraftPatch
) -> LaunchDraft:
    """A tap. The answers go on the patch that moves on, and only when they
    changed: going back to the words must not have the AI write them over."""
    sent = body.model_fields_set
    taps = kept.read(launch.id)
    pending = dict(taps.get("answers") or {})
    for field in ANSWER_KEYS:
        if field in sent:
            value = getattr(body, field)
            pending[field] = value.model_dump() if isinstance(value, Money) else value
    taps["answers"] = pending
    for field in ("goal_mode", "goal_words"):
        if field in sent:
            taps[field] = getattr(body, field)
    kept.write(launch.id, taps)
    waiting = not launch.ai_written_at and launch.status != LaunchStatus.BUILDING
    if body.step and body.step != "plan" and (pending or waiting):
        _send_answers(db, user=user, launch=launch, pending=pending)
        taps.pop("answers", None)
    if body.step:
        taps["step"] = body.step
    kept.write(launch.id, taps)
    db.refresh(launch)
    return read_google(db, launch)


def create_google(db: Session, *, user: User, launch: GoogleLaunch) -> LaunchDraft:
    """«Yaratish», and «Qayta urinish» after a refusal."""
    google_routes.create(launch.id, db, user)
    taps = kept.read(launch.id)
    taps["step"] = "review"
    kept.write(launch.id, taps)
    db.refresh(launch)
    return read_google(db, launch)


def retry_google(db: Session, *, user: User, launch: GoogleLaunch) -> LaunchDraft:
    """Words never written are asked again; refused words are sent again."""
    if launch.ai_written_at:
        return create_google(db, user=user, launch=launch)
    _send_answers(db, user=user, launch=launch, pending={})
    db.refresh(launch)
    return read_google(db, launch)


@router.get("/{draft_id}/areas", response_model=list[Area])
def areas(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> list[Area]:
    """The places the answers step offers."""
    launch = google_routes.google_launch(db, user=user, launch_id=draft_id)
    profile = launch_profile(db, launch=launch)
    country = profile.country_code if profile else ""
    options = area_options(db, country_code=country) if country else []
    return [Area.model_validate(row) for row in areas_of(options)]


@router.put("/{draft_id}/google", response_model=LaunchDraft)
def save_words(
    draft_id: uuid.UUID, body: GoogleWords, db: Db, user: CurrentUser
) -> LaunchDraft:
    """The words, and the site when it changed there: then the review."""
    launch = google_routes.google_launch(db, user=user, launch_id=draft_id)
    if body.url and body.url != launch.final_url:
        try:
            committed(
                db,
                lambda: google_services.change_google_site(
                    db, user=user, launch=launch, final_url=body.url
                ),
            )
        except DomainError as refusal:
            if refusal.code != "google_website_required":
                raise
            raise _on_field(refusal, "url") from refusal
    google_routes.save_words(
        draft_id,
        WordsIn(
            keywords=[row.text.strip() for row in body.keywords if row.text.strip()],
            negative_keywords=[word.strip() for word in body.minus if word.strip()],
            headlines=[line.strip() for line in body.headlines if line.strip()],
            descriptions=[line.strip() for line in body.descriptions if line.strip()],
            path1=body.paths[0] if body.paths else "",
            path2=body.paths[1] if len(body.paths) > 1 else "",
        ),
        db,
        user,
    )
    taps = kept.read(draft_id)
    taps["step"] = "review"
    kept.write(draft_id, taps)
    db.refresh(launch)
    return read_google(db, launch)


__all__ = [
    "create_google",
    "google_of",
    "patch_google",
    "read_google",
    "retry_google",
    "router",
    "start_google",
]
