"""The review screen and every press on and around it.

``GET /review`` is the whole screen; while ``state.keep_polling`` holds,
poll ``GET /review/state?tries=n`` - the cheap half - until it stops.
``POST /edit`` saves every section that was sent, all or nothing; a refusal
is a 422 whose ``problems`` maps ``section.field`` to its sentence.

``POST /create`` sends the proposal to the provider and spends money, so it
is a press of its own, as is ``POST /start``, which switches delivery on.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import LAUNCH_NAME_MAX, STARTABLE
from app.modules.ads.inputs.proposal import ProposalIn, check_proposal
from app.modules.ads.launch_schemas import ReviewOut, ReviewPollOut, ReviewRetryOut
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers.launch_common import (
    attempted,
    committed,
    encoded,
    launch_business,
    launch_head,
    owned_launch,
    writable_launch,
)
from app.modules.ads.selectors.campaign_type import picker_v2_on
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.launched import launched_targets
from app.modules.ads.selectors.review import review_state, shows_proposal
from app.modules.ads.selectors.review_proposal import proposal_view
from app.modules.ads.selectors.variants import variants_needing_words
from app.modules.ads.services import creation, sections, variants
from app.modules.ads.services import launch as launch_services
from app.modules.ads.services.advanced import rename_campaign
from app.modules.ads.services.locations import request_parents_if_unchecked
from app.modules.ads.services.manage import start_delivery
from app.modules.ads.services.save_proposal import save_proposal
from app.modules.ads.services.targeting import welcome_greeting, welcome_questions
from app.modules.businesses.selectors import business_for_page
from app.modules.integrations.services.connect import confirm_action_taken
from app.modules.integrations.services.sync import refresh_targets_if_stale
from app.modules.leads.services import request_forms_refresh

router = APIRouter(prefix="/launch", tags=["launch"])
TRIES_Q = Query(0, ge=0, description="The last answer's `tries`.")


class CreateIn(BaseModel):
    confirmed: bool = Field(
        False, description="The owner says the account's pending action is done."
    )


class NameIn(BaseModel):
    name: str = Field("", max_length=LAUNCH_NAME_MAX)


def _state(
    db: Session, *, launch: CampaignLaunch, now: Any, shown: str, tries: int
) -> dict[str, Any]:
    """The review state; a refusal nobody has an answer for yet is sent to be explained."""
    from app.common.i18n import get_language
    from app.modules.chat.services.explain import explain_launch_later

    state = review_state(db, launch=launch, now=now, shown=shown, tries=tries)
    if state["explaining"]:
        explain_launch_later(launch=launch, language=get_language())
    return state


def _review(
    db: Session, *, launch: CampaignLaunch, user: User, tries: int, shown: str
) -> dict[str, Any]:
    now = utcnow()
    state = _state(db, launch=launch, now=now, shown=shown, tries=tries)
    answer: dict[str, Any] = {
        "launch": launch_head(launch),
        "state": state,
        "can_discard": launch_services.is_discardable(db, launch=launch),
        "proposal": None,
    }
    if shows_proposal(launch):
        business = business_for_page(db, owner=user, page=launch.page)
        greeting = (
            welcome_greeting(db, launch=launch, business=business)
            if business is not None
            else ""
        )
        answer["proposal"] = proposal_view(
            db, launch=launch, business=business, now=now, greeting=greeting
        ) | {"chat_questions": list(welcome_questions(db, launch=launch))}
        answer["writes_copy"] = bool(variants_needing_words(db, launch=launch))
    return encoded(answer)


def _side_reads(db: Session, *, launch: CampaignLaunch, user: User) -> None:
    """What opening the proposal sets going: fresh audiences, parent regions."""
    if not shows_proposal(launch):
        return
    refresh_targets_if_stale(db, owner=user)
    if launch.status in STARTABLE:
        request_parents_if_unchecked(db, launch)
    db.commit()


@router.get("/{launch_id}/review", responses={200: {"model": ReviewOut}})
def review(
    launch_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    shown: str = Query("", description="The preparing stage the page last drew."),
) -> dict[str, Any]:
    """The proposal, section by section, and where the launch stands."""
    launch = owned_launch(db, user=user, launch_id=launch_id)
    _side_reads(db, launch=launch, user=user)
    return _review(db, launch=launch, user=user, tries=0, shown=shown)


@router.get("/{launch_id}/review/state", responses={200: {"model": ReviewPollOut}})
def review_poll(
    launch_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    tries: int = TRIES_Q,
    shown: str = Query(""),
) -> dict[str, Any]:
    """The cheap half, for the progress poll. Stops itself after a while."""
    launch = owned_launch(db, user=user, launch_id=launch_id)
    state = _state(db, launch=launch, now=utcnow(), shown=shown, tries=tries + 1)
    return encoded({"launch": launch_head(launch), "state": state})


@router.post("/{launch_id}/retry", responses={200: {"model": ReviewRetryOut}})
def retry(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Ask for a proposal: again after a failure, or the first time."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    refusal = attempted(
        db, lambda: launch_services.request_preparation(db, launch=launch)
    )
    return _review(db, launch=launch, user=user, tries=0, shown="") | {
        "refusal": refusal
    }


@router.post("/{launch_id}/edit", responses={200: {"model": ReviewOut}})
def save_edit(
    launch_id: uuid.UUID, body: ProposalIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Every section sent, written in one go or not at all.

    A patch: a section or a field left out keeps what the launch holds, and
    ``null`` clears a field that may be empty. A section the goal does not
    draw (``form`` without a lead form, ``advanced`` without campaign types)
    is refused.
    """
    launch = writable_launch(db, user=user, launch_id=launch_id)
    business = launch_business(db, launch=launch)
    answers = check_proposal(
        db,
        launch=launch,
        business=business,
        body=body,
        plan_owns_kind=picker_v2_on(user=launch.owner),
    )
    committed(
        db, lambda: save_proposal(db, launch=launch, business=business, **answers)
    )
    return _review(db, launch=launch, user=user, tries=0, shown="")


@router.post("/{launch_id}/regenerate/{section}")
def regenerate(
    launch_id: uuid.UUID, section: str, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Ask for one section again. Once per section."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    try:
        committed(
            db,
            lambda: sections.request_regeneration(db, launch=launch, section=section),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bunday bo'lim yo'q.") from exc
    return launch_head(launch)


@router.post("/{launch_id}/name", responses={200: {"model": ReviewOut}})
def rename(
    launch_id: uuid.UUID, body: NameIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """The name on the card's heading, typed over the generated one."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    business = launch_business(db, launch=launch)
    committed(
        db,
        lambda: rename_campaign(db, launch=launch, business=business, name=body.name),
    )
    return _review(db, launch=launch, user=user, tries=0, shown="")


@router.post("/{launch_id}/budget/fit", responses={200: {"model": ReviewOut}})
def fit_budget(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Raise the daily budget enough for every advert's share."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    business = launch_business(db, launch=launch)
    committed(
        db,
        lambda: variants.raise_budget_for_ads(db, launch=launch, business=business),
    )
    return _review(db, launch=launch, user=user, tries=0, shown="")


@router.post("/{launch_id}/ads/trim", responses={200: {"model": ReviewOut}})
def trim_ads(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Keep only the adverts the budget carries, first ones first."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    committed(db, lambda: variants.keep_affordable_ads(db, launch=launch))
    return _review(db, launch=launch, user=user, tries=0, shown="")


@router.post(
    "/{launch_id}/ads/{position}/remove", responses={200: {"model": ReviewOut}}
)
def remove_ad(
    launch_id: uuid.UUID, position: int, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Drop one advert - its picture and its words."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    committed(db, lambda: variants.remove_variant(db, launch=launch, position=position))
    return _review(db, launch=launch, user=user, tries=0, shown="")


@router.post("/{launch_id}/forms/refresh")
def refresh_forms(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, str]:
    """Ask the provider for this page's lead forms again, now."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    page = launch_page(db, launch=launch)
    committed(db, lambda: request_forms_refresh(db, owner=user, page=page))
    return {"detail": "Formalar so'raldi. Bir necha soniyadan keyin yangilang."}


@router.post("/{launch_id}/create", responses={200: {"model": ReviewOut}})
def create(
    launch_id: uuid.UUID, body: CreateIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Create the campaign at the provider. This is the press that spends."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    business = launch_business(db, launch=launch)
    if body.confirmed:
        confirm_action_taken(db, user=user)
    committed(
        db, lambda: creation.request_creation(db, launch=launch, business=business)
    )
    return _review(db, launch=launch, user=user, tries=0, shown="")


@router.post("/{launch_id}/start")
def start_ads(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Switch on everything this launch created."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    outcome = committed(
        db,
        lambda: start_delivery(db, user=user, targets=launched_targets(launch=launch)),
    )
    committed(
        db,
        lambda: creation.record_delivery(db, launch=launch, refused=outcome.refused),
    )
    return {
        "launch": launch_head(launch),
        "opened": len(outcome.opened),
        "refused": list(outcome.refused),
        "detail": "Reklama yoqildi. Bir necha daqiqadan keyin ko'rsatila boshlaydi."
        if outcome.opened
        else "",
    }


@router.post("/{launch_id}/discard")
def discard(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, str]:
    """Throw the preparation away."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    committed(db, lambda: launch_services.discard_launch(db, launch=launch))
    return {"detail": "Tayyorlash o'chirildi."}


@router.post("/{launch_id}/clean-up", responses={200: {"model": ReviewOut}})
def clean_up(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Remove what a failed creation left at the provider."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    if launch.error_code == "account_action":
        confirm_action_taken(db, user=user)
    committed(db, lambda: launch_services.request_cleanup(db, launch=launch))
    return _review(db, launch=launch, user=user, tries=0, shown="")
