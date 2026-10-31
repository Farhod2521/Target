"""The business directions customers pick from, as JSON. Superuser only.

A direction can only point at a preset that exists: a preset is a catalogue
file, and a profile on a direction whose preset has no file is refused every
advert (``profile_incomplete``). A new kind of business needs a name here and
the nearest preset; a new preset needs a catalogue file and a deploy.
"""

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Db
from app.common.exceptions import InputRefused
from app.common.presets import categories, label_for
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.permissions import superuser_required
from app.modules.backoffice.routers._out import choices
from app.modules.backoffice.schemas import (
    CreatedOut,
    DirectionOut,
    DirectionsOut,
    MessageOut,
)
from app.modules.backoffice.selectors.directions import (
    DirectionRow,
    businesses_on,
    direction_by_id,
    direction_rows,
)
from app.modules.businesses.models import BusinessCategory
from app.modules.businesses.schemas import CUSTOM

router = APIRouter(prefix="/directions")
Superuser = Annotated[User, Depends(superuser_required)]

# What the cabinet's «Boshqa» sends; a direction under these names is unreachable.
RESERVED_KEYS = {CUSTOM, "other"}
KEY_SHAPE = re.compile(r"[a-z0-9_]+")
SMALL = 32767


class DirectionIn(BaseModel):
    """One direction. Its key is set at creation and never edited."""

    label_uz: str = Field(max_length=64)
    label_ru: str = Field("", max_length=64)
    label_en: str = Field("", max_length=64)
    preset_key: str = Field(max_length=64, description="See `presets` on the list.")
    position: int = Field(0, ge=0, le=SMALL)
    is_active: bool = True


class NewDirectionIn(DirectionIn):
    key: str = Field(max_length=64, description="Latin letters, digits, `_`.")


def _columns(body: DirectionIn) -> dict[str, Any]:
    problems: dict[str, str] = {}
    label = body.label_uz.strip()
    if not label:
        problems["label_uz"] = "Nomini yozing."
    if body.preset_key not in {category.key for category in categories()}:
        problems["preset_key"] = "Katalogni ro'yxatdan tanlang."
    if problems:
        raise InputRefused(problems)
    return {
        "label_uz": label,
        "label_ru": body.label_ru.strip(),
        "label_en": body.label_en.strip(),
        "preset_key": body.preset_key,
        "position": body.position,
        "is_active": body.is_active,
    }


def _new_key(db: Db, raw: str) -> str:
    key = raw.strip().lower()
    if not KEY_SHAPE.fullmatch(key) or key in RESERVED_KEYS:
        raise InputRefused(
            {"key": "Kalit lotin harflari, raqam va «_» dan iborat bo'lsin."}
        )
    taken = select(BusinessCategory.id).where(BusinessCategory.key == key)
    if db.scalar(taken) is not None:
        raise InputRefused({"key": "Bu kalit allaqachon bor."})
    return key


def _direction(db: Db, direction_id: uuid.UUID) -> BusinessCategory:
    direction = direction_by_id(db, direction_id=direction_id)
    if direction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return direction


def direction_out(row: DirectionRow) -> dict[str, Any]:
    direction = row.direction
    return {
        "id": str(direction.id),
        "key": direction.key,
        "label_uz": direction.label_uz,
        "label_ru": direction.label_ru,
        "label_en": direction.label_en,
        "preset_key": direction.preset_key,
        "preset_label": label_for(category=direction.preset_key),
        "position": direction.position,
        "is_active": direction.is_active,
        "businesses": row.businesses,
        "created_at": direction.created_at,
    }


@router.get("", responses={200: {"model": DirectionsOut}})
def directions(db: Db, user: Superuser) -> dict[str, Any]:
    """Every direction, and the presets one may point at."""
    return {
        "rows": [direction_out(row) for row in direction_rows(db)],
        "presets": choices([(c.key, c.label) for c in categories()]),
    }


@router.get("/{direction_id}", responses={200: {"model": DirectionOut}})
def direction(direction_id: uuid.UUID, db: Db, user: Superuser) -> dict[str, Any]:
    """One direction, for the edit form."""
    row = _direction(db, direction_id)
    return direction_out(DirectionRow(row, businesses_on(db, direction=row)))


@router.post("", responses={200: {"model": CreatedOut}})
def create_direction(body: NewDirectionIn, db: Db, actor: Superuser) -> dict[str, Any]:
    """Write a new direction; customers see it at once when it is active."""
    data = _columns(body) | {"key": _new_key(db, body.key)}
    row = services.create_direction(db, data=data, actor=actor)
    db.commit()
    return {"message": "Yo'nalish yaratildi.", "id": str(row.id)}


@router.put("/{direction_id}", responses={200: {"model": MessageOut}})
def update_direction(
    direction_id: uuid.UUID, body: DirectionIn, db: Db, actor: Superuser
) -> dict[str, Any]:
    """Rewrite a direction; the profiles on it follow a new preset."""
    services.update_direction(
        db, direction=_direction(db, direction_id), data=_columns(body), actor=actor
    )
    db.commit()
    return {"message": "Yo'nalish yangilandi."}


@router.delete("/{direction_id}", responses={200: {"model": MessageOut}})
def delete_direction(
    direction_id: uuid.UUID, db: Db, actor: Superuser
) -> dict[str, Any]:
    """Delete a direction nobody stands on; a used one is switched off instead."""
    services.delete_direction(db, direction=_direction(db, direction_id), actor=actor)
    db.commit()
    return {"message": "Yo'nalish o'chirildi."}
