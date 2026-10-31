"""A new group in a campaign and a new advert in a group, from the targetologist's table.

Registered on the campaigns router. Each opens one change through the action
layer, and the screen follows it at ``/campaigns/actions/{id}``.
"""

import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from pydantic import Field
from pydantic.alias_generators import to_camel

from app.api.deps import CurrentUser, Db
from app.common.contract import Camel
from app.common.exceptions import InputRefused
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads import actions, selectors
from app.modules.ads.constants import LAUNCH_NAME_MAX, ManagedLevel
from app.modules.ads.contract.adverts import ad_edit_form
from app.modules.ads.contract.shapes import (
    AdditionStarted,
    NewAdForm,
    NewGroupForm,
)
from app.modules.ads.contract.words import network_of
from app.modules.ads.inputs import Problems
from app.modules.ads.inputs.budget import budget_minor
from app.modules.ads.routers import _detail, _target, router
from app.modules.ads.routers.editing import (
    HEADLINE_LIMIT,
    MESSAGE_LIMIT,
    _ad_forms,
    _ad_library,
)
from app.modules.ads.services.additions import (
    budget_holder,
    source_ad,
    source_group,
    story_of,
)
from app.modules.ads.services.swap import NAME_SUFFIX


class NewGroupIn(Camel):
    name: str = Field(min_length=1, max_length=LAUNCH_NAME_MAX)
    source: str = Field(
        default="", description="A group of this campaign; empty: its first."
    )
    daily_budget: Decimal | None = Field(
        default=None,
        gt=0,
        description="Required when `budgetAt` is `adset`, refused when it is `campaign`.",
    )


class NewAdIn(Camel):
    name: str = Field(min_length=1, max_length=LAUNCH_NAME_MAX)
    source: str = Field(
        default="", description="The advert to copy; empty: the nearest."
    )
    message: str | None = Field(default=None, max_length=MESSAGE_LIMIT)
    headline: str | None = Field(default=None, max_length=HEADLINE_LIMIT)
    description: str | None = Field(default=None, max_length=HEADLINE_LIMIT)
    picture: str | None = Field(default=None, description="A row of `library`.")
    lead_form: str | None = Field(
        default=None, description="A form of `forms.options`."
    )


def _places(row: Any) -> int:
    return provider_money(provider=row.provider).decimal_places(row.currency)


def _major(minor: int, places: int) -> float:
    return float(Decimal(minor).scaleb(-places))


@router.get("/{campaign_id}/adsets/new", response_model=NewGroupForm)
def new_group_form(campaign_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """What a new group copies from, and whether it takes a budget of its own."""
    campaign = _detail(db, user, campaign_id)
    source = source_group(campaign=campaign)
    places = _places(source)
    return {
        "campaign": {"id": str(campaign.id), "name": campaign.name},
        "network": network_of(campaign.provider),
        "budget_at": budget_holder(campaign=campaign),
        "currency": source.currency,
        "min_budget": _major(
            selectors.budget_floor(target=source, level=ManagedLevel.ADSET), places
        ),
        "groups": [
            {"external_id": row.external_id, "name": row.name}
            for row in campaign.adsets
        ],
    }


@router.post(
    "/{campaign_id}/adsets",
    response_model=AdditionStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
def new_group(
    campaign_id: uuid.UUID, body: NewGroupIn, db: Db, user: CurrentUser
) -> dict[str, str]:
    """Open a paused copy of one of this campaign's groups."""
    campaign = _detail(db, user, campaign_id)
    log = actions.request(
        db,
        user=user,
        ask=actions.NewGroup(
            external_id=campaign.external_id,
            name=body.name.strip(),
            source=body.source,
            daily_budget_minor=_budget(body, campaign),
        ),
    )
    db.commit()
    return {"action_id": str(log.id)}


def _budget(body: NewGroupIn, campaign: Any) -> int | None:
    if body.daily_budget is None:
        return None
    problems = Problems()
    source = source_group(campaign=campaign, external_id=body.source)
    asked = budget_minor(
        body.daily_budget,
        currency=source.currency,
        money=provider_money(provider=source.provider),
        floor_minor=selectors.budget_floor(target=source, level=ManagedLevel.ADSET),
        problems=problems,
    )
    try:
        problems.refuse()
    except InputRefused as exc:
        raise InputRefused(
            {to_camel(key): words for key, words in exc.problems.items()}
        ) from None
    return asked


def _copied(db: Db, user: User, group: Any, source: str = "") -> Any:
    return source_ad(db, owner=user, group=group, external_id=source)


@router.get("/adsets/{external_id}/ads/new", response_model=NewAdForm)
def new_ad_form(external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    """The advert a new one starts from, the pictures it may take, and the forms."""
    group = _target(db, user, ManagedLevel.ADSET, external_id)
    ad = _copied(db, user, group)
    content = selectors.creative_of(db, owner=user, ad=ad)
    return ad_edit_form(
        ad,
        initial={
            "message": getattr(content, "message", "") or "",
            "headline": getattr(content, "headline", "") or "",
            "description": getattr(content, "description", "") or "",
        },
        can_swap=story_of(db, owner=user, ad=ad) is not None,
        library=[selectors.asset_row(row) for row in _ad_library(db, user, ad)],
        forms=_ad_forms(db, user, ad),
        limits={"headline": HEADLINE_LIMIT, "message": MESSAGE_LIMIT},
        early_hours=0,
    ) | {
        "group": group.external_id,
        "name": f"{ad.name}{NAME_SUFFIX}",
        "warns_learning": group.is_learning,
    }


@router.post(
    "/adsets/{external_id}/ads",
    response_model=AdditionStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
def new_ad(
    external_id: str, body: NewAdIn, db: Db, user: CurrentUser
) -> dict[str, str]:
    """Open a paused copy of an advert in this group, with what was typed changed."""
    group = _target(db, user, ManagedLevel.ADSET, external_id)
    ad = _copied(db, user, group, body.source)
    if (body.picture or "") and (body.picture or "") not in {
        str(row.id) for row in _ad_library(db, user, ad)
    }:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bu rasm kutubxonada yo'q."
        )
    log = actions.request(
        db,
        user=user,
        ask=actions.NewAd(
            external_id=group.external_id,
            name=body.name.strip(),
            message=body.message,
            headline=body.headline,
            description=body.description,
            asset_id=body.picture or "",
            lead_form_id=body.lead_form or "",
            source=ad.external_id,
        ),
    )
    db.commit()
    return {"action_id": str(log.id)}
