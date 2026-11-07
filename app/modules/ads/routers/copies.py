"""TZ 2: «Duplikat» on a campaign, a group and an advert.

Each opens a change the worker carries out; the screen follows it at
``/campaigns/actions/{id}``. The two reads are what the dialog offers: the
campaigns a group may go into, the groups an advert may go into.
"""

import uuid
from typing import Any

from fastapi import status
from metaads.campaigns import REMOVED_STATUSES
from pydantic import Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Db
from app.common.contract import Camel
from app.modules.ads import actions
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.contract.shapes import AdditionStarted
from app.modules.ads.models import Campaign
from app.modules.ads.routers import _detail, _target, router
from app.modules.ads.selectors.pages import campaign_on_page
from app.modules.ads.services.copies import NEW_GROUP
from core.agent.guardrails import ACTIVE, FINISHED


class CopyInto(Camel):
    into: str = Field(
        default="",
        description="A group's campaign or an advert's group (external id); "
        "`new` puts an advert in a new group; empty keeps the original's.",
    )


class CopyPlace(Camel):
    id: str
    name: str
    running: bool
    own: bool = Field(description="The original's own campaign or group.")


class CopyPlaces(Camel):
    places: list[CopyPlace]


def _started(
    db: Db, user: Any, *, level: str, external_id: str, into: str
) -> dict[str, str]:
    log = actions.request(
        db,
        user=user,
        ask=actions.Copy(level=level, external_id=external_id, into=into),
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
        if _open(row) and campaign_on_page(db, owner=user, campaign=row)
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
    """TZ 2.3: the advert as it is - into a running group active, into a new one paused."""
    _target(db, user, ManagedLevel.AD, external_id)
    return _started(
        db, user, level=ManagedLevel.AD, external_id=external_id, into=body.into
    )


__all__ = ["NEW_GROUP"]
