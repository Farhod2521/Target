"""What each kind of business is advised, and the narrower kinds under it,
as JSON. For the Owner and the Engineer.

A direction's advice is five things the office writes once and every
business of that direction is offered: the goal to offer first and why, the
second goal and when it is the better one, and what an advert must not say.

The narrower kinds («Oshxona mebeli» under «Mebel») are not typed in here:
the assistant makes one the first time a customer names it. This is where
the office looks at what it made: marks one checked, gives it other words it
is known by, switches it off, or merges two that are one.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Db
from app.modules.accounts.models import User
from app.modules.backoffice.constants import BUSINESS_TYPE_ROLES, ActionKind
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import choices
from app.modules.backoffice.services.journal import record
from app.modules.businesses.constants import (
    ADVISED_GOAL_LABELS,
    AdvisedGoal,
    SubtypeOrigin,
)
from app.modules.businesses.models import (
    Business,
    BusinessCategory,
    BusinessKnowledge,
    BusinessSubtype,
    BusinessTypeRule,
)
from app.modules.businesses.services import advice as advice_services
from app.modules.businesses.services import subtypes as subtype_services

router = APIRouter(tags=["office business types"])
Keeper = Annotated[User, Depends(staff_required(*BUSINESS_TYPE_ROLES))]


class RuleIn(BaseModel):
    goal_first: str = Field("", max_length=32, description="See `goals` on the row.")
    reason_first: str = Field("", description="Shown to the customer as written.")
    goal_second: str = Field("", max_length=32)
    when_second: str = ""
    never_say: str = ""


class SubtypeIn(BaseModel):
    name: str = Field(max_length=80)
    synonyms: list[str] = Field(default_factory=list, max_length=30)


class SubtypePatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    synonyms: list[str] | None = Field(None, max_length=30)
    is_checked: bool | None = None
    is_active: bool | None = None


class MergeIn(BaseModel):
    into_id: uuid.UUID


def _direction(db: Session, direction_id: uuid.UUID) -> BusinessCategory:
    direction = db.get(BusinessCategory, direction_id)
    if direction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return direction


def _subtype(db: Session, subtype_id: uuid.UUID) -> BusinessSubtype:
    subtype = db.get(BusinessSubtype, subtype_id)
    if subtype is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return subtype


def _goal(key: str) -> dict[str, str] | None:
    if not key:
        return None
    try:
        return {"key": key, "label": ADVISED_GOAL_LABELS[AdvisedGoal(key)]}
    except ValueError:
        return {"key": key, "label": key}


def _rule_out(rule: BusinessTypeRule | None) -> dict[str, Any]:
    return {
        "goal_first": _goal(rule.goal_first) if rule else None,
        "reason_first": rule.reason_first if rule else "",
        "goal_second": _goal(rule.goal_second) if rule else None,
        "when_second": rule.when_second if rule else "",
        "never_say": rule.never_say if rule else "",
        "updated_at": rule.updated_at if rule else None,
    }


def _type_out(
    direction: BusinessCategory,
    rule: BusinessTypeRule | None,
    *,
    businesses: int,
    subtypes: int,
    unchecked: int,
) -> dict[str, Any]:
    allowed = advice_services.runnable(direction)
    return {
        "id": str(direction.id),
        "key": direction.key,
        "label": direction.label_uz,
        "is_active": direction.is_active,
        "businesses": businesses,
        "subtypes": subtypes,
        "unchecked_subtypes": unchecked,
        "is_advised": bool(rule and rule.goal_first),
        "rule": _rule_out(rule),
        "goals": choices(
            [
                (goal.value, ADVISED_GOAL_LABELS[goal])
                for goal in AdvisedGoal
                if goal.value in allowed
            ]
        ),
    }


def _counts(db: Session) -> tuple[dict[Any, int], dict[Any, int], dict[Any, int]]:
    businesses = dict(
        db.execute(
            select(Business.direction_id, func.count(Business.id))
            .where(Business.direction_id.is_not(None))
            .group_by(Business.direction_id)
        ).all()
    )
    live = (
        BusinessSubtype.is_active.is_(True),
        BusinessSubtype.merged_into_id.is_(None),
    )
    subtypes = dict(
        db.execute(
            select(BusinessSubtype.direction_id, func.count(BusinessSubtype.id))
            .where(*live)
            .group_by(BusinessSubtype.direction_id)
        ).all()
    )
    unchecked = dict(
        db.execute(
            select(BusinessSubtype.direction_id, func.count(BusinessSubtype.id))
            .where(*live, BusinessSubtype.is_checked.is_(False))
            .group_by(BusinessSubtype.direction_id)
        ).all()
    )
    return businesses, subtypes, unchecked


@router.get("/business-types")
def business_types(db: Db, user: Keeper) -> dict[str, Any]:
    """Every direction with its advice, the goals it may be advised, and how
    many businesses and narrower kinds stand under it."""
    rules = {rule.direction_id: rule for rule in db.scalars(select(BusinessTypeRule))}
    businesses, subtypes, unchecked = _counts(db)
    rows = db.scalars(
        select(BusinessCategory).order_by(
            BusinessCategory.position, BusinessCategory.key
        )
    )
    return {
        "rows": [
            _type_out(
                row,
                rules.get(row.id),
                businesses=businesses.get(row.id, 0),
                subtypes=subtypes.get(row.id, 0),
                unchecked=unchecked.get(row.id, 0),
            )
            for row in rows
        ]
    }


@router.put("/business-types/{direction_id}/rule")
def save_rule(
    direction_id: uuid.UUID, body: RuleIn, db: Db, actor: Keeper
) -> dict[str, Any]:
    """Write a direction's advice over what was there. An empty first goal
    takes the advice back: the direction is advised nothing."""
    direction = _direction(db, direction_id)
    rule = advice_services.save_rule(
        db,
        direction=direction,
        goal_first=body.goal_first,
        reason_first=body.reason_first,
        goal_second=body.goal_second,
        when_second=body.when_second,
        never_say=body.never_say,
        actor=actor,
    )
    record(
        db,
        customer=actor,
        actor=actor,
        kind=ActionKind.TYPE_RULE_SAVED,
        detail={
            "key": direction.key,
            "goal_first": rule.goal_first,
            "goal_second": rule.goal_second,
        },
    )
    db.commit()
    return {"message": "Tavsiya saqlandi.", "rule": _rule_out(rule)}


def _subtype_out(row: BusinessSubtype, *, businesses: int = 0) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "direction_id": str(row.direction_id),
        "name": row.name,
        "synonyms": list(row.synonyms or []),
        "origin": row.origin,
        "is_checked": row.is_checked,
        "is_active": row.is_active,
        "merged_into_id": str(row.merged_into_id) if row.merged_into_id else None,
        "businesses": businesses,
        "created_at": row.created_at,
    }


@router.get("/business-types/{direction_id}/subtypes")
def subtypes_of(
    direction_id: uuid.UUID, db: Db, user: Keeper, merged: bool = False
) -> dict[str, Any]:
    """The narrower kinds under a direction, the unchecked first, with how
    many businesses stand on each. ``merged=true`` adds the ones given up."""
    direction = _direction(db, direction_id)
    counts = dict(
        db.execute(
            select(BusinessKnowledge.subtype_id, func.count(BusinessKnowledge.id))
            .where(BusinessKnowledge.subtype_id.is_not(None))
            .group_by(BusinessKnowledge.subtype_id)
        ).all()
    )
    query = select(BusinessSubtype).where(BusinessSubtype.direction_id == direction.id)
    if not merged:
        query = query.where(BusinessSubtype.merged_into_id.is_(None))
    rows = db.scalars(
        query.order_by(BusinessSubtype.is_checked, BusinessSubtype.name_key)
    )
    return {
        "direction": {
            "id": str(direction.id),
            "key": direction.key,
            "label": direction.label_uz,
        },
        "rows": [_subtype_out(row, businesses=counts.get(row.id, 0)) for row in rows],
    }


@router.post(
    "/business-types/{direction_id}/subtypes", status_code=status.HTTP_201_CREATED
)
def create_subtype(
    direction_id: uuid.UUID, body: SubtypeIn, db: Db, actor: Keeper
) -> dict[str, Any]:
    """Write a narrower kind by hand. A name already there, under its own
    name or as another word for a kind, answers that kind and makes nothing."""
    direction = _direction(db, direction_id)
    row, made = subtype_services.ensure(
        db,
        direction=direction,
        name=body.name,
        synonyms=body.synonyms,
        origin=SubtypeOrigin.STAFF,
        actor=actor,
    )
    if made:
        record(
            db,
            customer=actor,
            actor=actor,
            kind=ActionKind.SUBTYPE_CREATED,
            detail={"key": direction.key, "name": row.name},
        )
    db.commit()
    return {
        "message": "Yo'nalish yaratildi."
        if made
        else "Bunday yo'nalish allaqachon bor.",
        "created": made,
        "subtype": _subtype_out(row),
    }


@router.patch("/business-subtypes/{subtype_id}")
def change_subtype(
    subtype_id: uuid.UUID, body: SubtypePatch, db: Db, actor: Keeper
) -> dict[str, Any]:
    """Rename a kind, give it other words, mark it checked, switch it off."""
    row = _subtype(db, subtype_id)
    before = {
        "name": row.name,
        "is_checked": row.is_checked,
        "is_active": row.is_active,
    }
    subtype_services.change(
        db,
        subtype=row,
        name=body.name,
        synonyms=body.synonyms,
        is_checked=body.is_checked,
        is_active=body.is_active,
    )
    record(
        db,
        customer=actor,
        actor=actor,
        kind=ActionKind.SUBTYPE_CHANGED,
        detail={
            "before": before,
            "after": {
                "name": row.name,
                "is_checked": row.is_checked,
                "is_active": row.is_active,
            },
        },
    )
    db.commit()
    return {"message": "Yo'nalish yangilandi.", "subtype": _subtype_out(row)}


@router.post("/business-subtypes/{subtype_id}/merge")
def merge_subtype(
    subtype_id: uuid.UUID, body: MergeIn, db: Db, actor: Keeper
) -> dict[str, Any]:
    """Give this kind up for another of the same direction: its businesses
    move, its name becomes another word for the kind kept."""
    source, target = _subtype(db, subtype_id), _subtype(db, body.into_id)
    gone = source.name
    kept = subtype_services.merge(db, source=source, target=target)
    record(
        db,
        customer=actor,
        actor=actor,
        kind=ActionKind.SUBTYPE_MERGED,
        detail={"from": gone, "into": kept.name},
    )
    db.commit()
    return {"message": "Yo'nalishlar birlashtirildi.", "subtype": _subtype_out(kept)}
