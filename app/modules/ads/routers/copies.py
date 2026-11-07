"""TZ 2: «Duplikat» on a campaign, a group and an advert.

Each opens a change the worker carries out; the screen follows it at
``/campaigns/actions/{id}``. The two reads are what the dialog offers: the
campaigns a group may go into, the groups an advert may go into.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from metaads.campaigns import REMOVED_STATUSES
from metaads.restage import button_of, welcome_of
from pydantic import Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Db
from app.common.contract import Camel
from app.modules.ads import actions, selectors
from app.modules.ads.constants import BUTTON_LABELS, ManagedLevel
from app.modules.ads.contract.adverts import ad_edit_form
from app.modules.ads.contract.shapes import AdditionStarted, AdEdit
from app.modules.ads.models import Campaign
from app.modules.ads.routers import _detail, _target, router
from app.modules.ads.routers.editing import (
    HEADLINE_LIMIT,
    MESSAGE_LIMIT,
    WelcomeIn,
    _ad_forms,
    _ad_library,
)
from app.modules.ads.selectors.pages import campaign_on_page
from app.modules.ads.services.additions import story_of
from app.modules.ads.services.copies import NEW_GROUP, offered_buttons, same_budget
from core.agent.guardrails import ACTIVE, FINISHED


class NewCreative(Camel):
    """TZ 2.3: what the advert's copy says and shows instead of the original."""

    message: str | None = Field(default=None, max_length=MESSAGE_LIMIT)
    headline: str | None = Field(default=None, max_length=HEADLINE_LIMIT)
    description: str | None = Field(default=None, max_length=HEADLINE_LIMIT)
    picture: str | None = Field(default=None, description="A row of `library`.")
    lead_form: str | None = Field(
        default=None, description="A form of `forms.options`."
    )
    button: str | None = Field(default=None, description="A key of `buttons`.")
    welcome: WelcomeIn | None = Field(
        default=None, description="A chat advert's greeting (TZ 2.5)."
    )


class CopyInto(Camel):
    into: str = Field(
        default="",
        description="A group's campaign or an advert's group (external id); "
        "`new` puts an advert in a new group; empty keeps the original's.",
    )
    creative: NewCreative | None = Field(
        default=None,
        description="An advert only: a new creative; left out, the original's.",
    )


class ButtonChoice(Camel):
    key: str
    label: str


class CopyCreativeForm(AdEdit):
    """The advert's creative as it is, and what a new one may take instead."""

    button: str = Field(description="The button's word now; empty: none to change.")
    buttons: list[ButtonChoice] = Field(
        description="Its own first; only it when the word cannot change."
    )


class CopyPlace(Camel):
    id: str
    name: str
    running: bool
    own: bool = Field(description="The original's own campaign or group.")


class CopyPlaces(Camel):
    places: list[CopyPlace]


def _started(
    db: Db,
    user: Any,
    *,
    level: str,
    external_id: str,
    into: str,
    creative: dict[str, Any] | None = None,
) -> dict[str, str]:
    log = actions.request(
        db,
        user=user,
        ask=actions.Copy(
            level=level, external_id=external_id, into=into, creative=creative
        ),
    )
    db.commit()
    return {"action_id": str(log.id)}


def _place(row: Any, *, own: Any) -> dict[str, Any]:
    return {
        "id": row.external_id,
        "name": row.name or row.external_id,
        "running": str(row.delivery) == ACTIVE,
        "own": row.id == own.id,
    }


def _open(row: Any) -> bool:
    return (
        str(row.status).upper() not in REMOVED_STATUSES
        and str(row.delivery) != FINISHED
    )


@router.post(
    "/{campaign_id}/copy",
    response_model=AdditionStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
def copy_campaign(campaign_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, str]:
    """TZ 2.1: the campaign, its groups and adverts, paused, named «… — nusxa»."""
    campaign = _detail(db, user, campaign_id)
    return _started(
        db, user, level=ManagedLevel.CAMPAIGN, external_id=campaign.external_id, into=""
    )


@router.get("/adsets/{external_id}/copy", response_model=CopyPlaces)
def copy_group_places(external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    """The campaigns a group's copy may go into: its own first, then the account's."""
    group = _target(db, user, ManagedLevel.ADSET, external_id)
    own = group.campaign
    others = db.scalars(
        select(Campaign).where(
            Campaign.owner_id == user.id,
            Campaign.ad_account_id == own.ad_account_id,
            Campaign.provider == own.provider,
            Campaign.id != own.id,
        )
    )
    shown = [
        row
        for row in others
        if _open(row)
        and same_budget(row, own)
        and campaign_on_page(db, owner=user, campaign=row)
    ]
    return {"places": [_place(row, own=own) for row in [own, *shown]]}


@router.post(
    "/adsets/{external_id}/copy",
    response_model=AdditionStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
def copy_group(
    external_id: str, body: CopyInto, db: Db, user: CurrentUser
) -> dict[str, str]:
    """TZ 2.2: the group with its adverts, paused, into this or another campaign."""
    _target(db, user, ManagedLevel.ADSET, external_id)
    return _started(
        db, user, level=ManagedLevel.ADSET, external_id=external_id, into=body.into
    )


@router.get("/ads/{external_id}/copy", response_model=CopyPlaces)
def copy_ad_places(external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    """The groups an advert's copy may go into: its own first, then the campaign's."""
    ad = _target(db, user, ManagedLevel.AD, external_id)
    own = ad.adset
    rows = [
        own,
        *(row for row in own.campaign.adsets if row.id != own.id and _open(row)),
    ]
    return {"places": [_place(row, own=own) for row in rows]}


@router.post(
    "/ads/{external_id}/copy",
    response_model=AdditionStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
def copy_ad(
    external_id: str, body: CopyInto, db: Db, user: CurrentUser
) -> dict[str, str]:
    """TZ 2.3: the advert - into a running group active, into a new one paused.

    With ``creative`` it carries a new picture, words, form or button instead
    of the original's creative.
    """
    ad = _target(db, user, ManagedLevel.AD, external_id)
    creative = None
    if body.creative is not None:
        asked = body.creative
        picture = asked.picture or ""
        if picture and picture not in {
            str(row.id) for row in _ad_library(db, user, ad)
        }:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bu rasm kutubxonada yo'q.",
            )
        creative = {
            "message": asked.message,
            "headline": asked.headline,
            "description": asked.description,
            "asset_id": picture,
            "lead_form_id": asked.lead_form or "",
            "button": asked.button or "",
            "welcome": asked.welcome.model_dump() if asked.welcome else None,
        }
    return _started(
        db,
        user,
        level=ManagedLevel.AD,
        external_id=external_id,
        into=body.into,
        creative=creative,
    )


@router.get("/ads/{external_id}/copy/creative", response_model=CopyCreativeForm)
def copy_ad_creative(external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    """TZ 2.3: the original's words, the library, the forms and the buttons."""
    ad = _target(db, user, ManagedLevel.AD, external_id)
    content = selectors.creative_of(db, owner=user, ad=ad)
    story = story_of(db, owner=user, ad=ad)
    keys = offered_buttons(story) if story is not None else ()
    return ad_edit_form(
        ad,
        initial={
            "message": getattr(content, "message", "") or "",
            "headline": getattr(content, "headline", "") or "",
            "description": getattr(content, "description", "") or "",
        },
        can_swap=story is not None,
        library=[selectors.asset_row(row) for row in _ad_library(db, user, ad)],
        forms=_ad_forms(db, user, ad),
        limits={"headline": HEADLINE_LIMIT, "message": MESSAGE_LIMIT},
        early_hours=0,
        welcome=welcome_of(story) if story is not None else None,
    ) | {
        "button": str(button_of(story).get("type") or ""),
        "buttons": [{"key": key, "label": BUTTON_LABELS.get(key, key)} for key in keys],
    }


__all__ = ["NEW_GROUP"]
