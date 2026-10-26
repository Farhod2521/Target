"""The lead form a launch collects answers with, and its depth.

``GET /form`` is the picker: the page's forms, or a builder for a new one.
``POST /form`` saves the answer; ``POST /form/auto`` hands it back to the
rules. ``POST /form/refresh`` asks the provider for the page's forms again;
poll ``GET /form?since=..&tries=n`` while ``forms_pending`` holds.

``POST /form-depth/{depth}`` asks for one depth's questions to be written;
poll ``GET /form-depth/{depth}?tries=n`` while ``keep_polling`` holds.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.common.exceptions import NotFound
from app.modules.ads import naming
from app.modules.ads.constants import (
    LEAD_FORM_NAME,
    LEAD_FORM_QUESTIONS,
    MAX_CUSTOM_QUESTIONS,
    MAX_FORMS_POLLS,
    MAX_OPTIONS,
    QUESTION_TYPES,
    FormDepth,
)
from app.modules.ads.inputs.lead_form import DEFAULT_KINDS, LeadFormPickIn, check_pick
from app.modules.ads.inputs.questions import MAX_QUESTIONS
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers.launch_common import (
    attempted,
    committed,
    encoded,
    owned_launch,
    writable_launch,
)
from app.modules.ads.selectors.goals import goal_preset
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.lead_form import (
    default_title,
    ending_fields,
    form_choice,
    polled_block,
    stored_ending,
)
from app.modules.ads.services import forms
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import business_for_page
from app.modules.leads.constants import PICKER_FORMS, QUESTION_LABELS
from app.modules.leads.selectors.reads import FormChoices, form_names, usable_forms
from app.modules.leads.services import request_forms_refresh

router = APIRouter(prefix="/launch", tags=["launch: lead form"])
MAX_DEPTH_POLLS = 30


class AutoIn(BaseModel):
    goal: str = ""
    depth: str = ""


def _collecting(db: Session, *, launch: CampaignLaunch, goal: str = "") -> None:
    """Only a launch whose advert carries a form has a form to pick."""
    preset = goal_preset(db, launch=launch, goal=goal)
    if preset is None or not preset.needs_lead_form:
        raise NotFound("Bu reklamada forma yo'q.")


def _business(db: Session, launch: CampaignLaunch) -> Business | None:
    return business_for_page(db, owner=launch.owner, page=launch.page)


def _offered(db: Session, launch: CampaignLaunch) -> FormChoices:
    page = launch_page(db, launch=launch)
    if page is None:
        return FormChoices(options=(), hidden=0)
    return usable_forms(db, owner=launch.owner, page=page, limit=None)


def _stamp(at: datetime | None) -> str:
    return str(int(at.timestamp())) if at is not None else ""


def _picker(
    db: Session, *, launch: CampaignLaunch, goal: str, since: str, tries: int
) -> dict[str, Any]:
    offered = _offered(db, launch)
    page = launch_page(db, launch=launch)
    synced = page.forms_synced_at if page is not None else None
    business = _business(db, launch)
    asked = launch.answers.get(LEAD_FORM_QUESTIONS)
    if asked is None:
        asked = [{"kind": kind, "label": ""} for kind in DEFAULT_KINDS]
    chosen = {str(item.get("kind", "")) for item in asked}
    building = not launch.lead_form_external_id and (
        bool(launch.answers.get(LEAD_FORM_QUESTIONS)) or not offered.options
    )
    stale = bool(since) and (not synced or _stamp(synced) <= since)
    return encoded(
        {
            "goal": goal,
            "lead_forms": offered.options,
            "picker_fold": PICKER_FORMS,
            "chosen_form": launch.lead_form_external_id,
            "standard_questions": [
                {
                    "kind": kind,
                    "label": QUESTION_LABELS.get(meta_type, kind),
                    "checked": kind in chosen,
                }
                for kind, meta_type in QUESTION_TYPES.items()
            ],
            "typed_questions": [
                {
                    "label": str(item.get("label", "")),
                    "options": item.get("options") or [],
                }
                for item in asked
                if str(item.get("kind", "")) not in QUESTION_TYPES
            ],
            "form_name": str(launch.answers.get(LEAD_FORM_NAME) or "")
            or _default_name(launch, business),
            "open_builder": building,
            "max_options": MAX_OPTIONS,
            "max_questions": MAX_QUESTIONS,
            "ending": ending_fields(
                ending=stored_ending(launch=launch), business=business
            )
            if business is not None
            else None,
            "forms_synced_at": synced,
            "forms_since": since,
            "forms_tries": tries,
            "forms_pending": (bool(since) or tries > 0)
            and stale
            and tries < MAX_FORMS_POLLS,
            "choice": form_choice(db, launch=launch),
        }
    )


def _default_name(launch: CampaignLaunch, business: Business | None) -> str:
    return naming.form_name(launch=launch, business=business) if business else ""


@router.get("/{launch_id}/form")
def lead_form(
    launch_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    goal: str = "",
    since: str = Query("", description="The last answer's `forms_since`."),
    tries: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Which form collects the answers - one of the page's, or a new one."""
    launch = owned_launch(db, user=user, launch_id=launch_id)
    _collecting(db, launch=launch, goal=goal)
    return _picker(
        db, launch=launch, goal=goal, since=since, tries=tries + 1 if since else 0
    )


@router.post("/{launch_id}/form")
def pick_form(
    launch_id: uuid.UUID, body: LeadFormPickIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """The answer, written once and read by everything downstream."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    _collecting(db, launch=launch, goal=body.goal)
    business = _business(db, launch)
    page = launch_page(db, launch=launch)
    external_id, questions, name, ending = check_pick(
        body,
        default_name=_default_name(launch, business),
        taken_names=form_names(db, owner=launch.owner, page=page)
        if page is not None
        else frozenset(),
        region=business.country_code if business is not None else "",
        default_title=default_title(business) if business is not None else "",
    )
    committed(
        db,
        lambda: forms.choose_lead_form(
            db,
            launch=launch,
            external_id=external_id,
            questions=questions,
            name=name,
            ending=ending,
        ),
    )
    db.refresh(launch)
    return encoded({"goal": body.goal, "choice": form_choice(db, launch=launch)})


@router.post("/{launch_id}/form/auto")
def form_by_ai(
    launch_id: uuid.UUID, body: AutoIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Hand the question back to the rules; clears the owner's answer."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    _collecting(db, launch=launch, goal=body.goal)
    committed(
        db,
        lambda: forms.let_ai_choose(db, launch=launch, depth=body.depth, now=utcnow()),
    )
    return encoded({"goal": body.goal, "choice": form_choice(db, launch=launch)})


@router.post("/{launch_id}/form/new")
def new_form(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Drop the chosen form so the launch builds its own."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    _collecting(db, launch=launch)
    committed(db, lambda: forms.choose_lead_form(db, launch=launch, external_id=""))
    return encoded({"choice": form_choice(db, launch=launch)})


@router.post("/{launch_id}/form/refresh")
def refresh_form_list(
    launch_id: uuid.UUID, db: Db, user: CurrentUser, goal: str = ""
) -> dict[str, Any]:
    """Ask the provider for this page's forms again, now."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    _collecting(db, launch=launch, goal=goal)
    page = launch_page(db, launch=launch)
    since = _stamp(page.forms_synced_at if page is not None else None) or "0"
    error = attempted(db, lambda: request_forms_refresh(db, owner=user, page=page))
    answer = _picker(
        db,
        launch=launch,
        goal=goal,
        since="" if error else since,
        tries=0 if error else 1,
    )
    return answer | {"error": error}


def _depth_block(
    launch: CampaignLaunch, *, depth: str, tries: int, refusal: str = ""
) -> dict[str, Any]:
    block = polled_block(launch=launch, depth=depth, now=utcnow())
    gave_up = tries >= MAX_DEPTH_POLLS
    return encoded(
        {
            "block": block,
            "max_options": MAX_OPTIONS,
            "max_custom": MAX_CUSTOM_QUESTIONS,
            "standard_kinds": list(QUESTION_TYPES),
            "tries": tries,
            "gave_up": gave_up,
            "keep_polling": block.state == "pending" and not gave_up,
            "refusal": refusal,
        }
    )


def _known(depth: str) -> None:
    if depth not in FormDepth.values:
        raise NotFound("Bunday chuqurlik yo'q.")


@router.get("/{launch_id}/form-depth/{depth}")
def form_depth(
    launch_id: uuid.UUID,
    depth: str,
    db: Db,
    user: CurrentUser,
    tries: int = Query(0, ge=0),
) -> dict[str, Any]:
    launch = owned_launch(db, user=user, launch_id=launch_id)
    _known(depth)
    return _depth_block(launch, depth=depth, tries=tries + 1)


@router.post("/{launch_id}/form-depth/{depth}")
def ask_form_depth(
    launch_id: uuid.UUID, depth: str, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Have this depth's questions written, unless they are or are being."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    _known(depth)
    refusal = attempted(
        db,
        lambda: forms.request_form_variant(
            db, launch=launch, depth=depth, now=utcnow()
        ),
    )
    return _depth_block(launch, depth=depth, tries=0, refusal=refusal)
