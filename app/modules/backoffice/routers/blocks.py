"""Block reasons and the accounts the system asks Support to block, as JSON.

The reasons are the super admin's: only a superuser writes them, and those
the code names (``code``) keep their place - their words may change, they
cannot be archived. Support and the owner read the list to block with.

The suggestions are the system's refusals handed to a person: Support
blocks the account from here, or lets it be.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.api.deps import Db
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.modules.accounts.models import BlockReason, BlockSuggestion, User
from app.modules.accounts.services import dismiss_suggestion
from app.modules.backoffice import services
from app.modules.backoffice.constants import BLOCK_ROLES
from app.modules.backoffice.exceptions import BlockReasonFixed
from app.modules.backoffice.permissions import staff_required, superuser_required
from app.modules.backoffice.routers._out import person_out
from app.modules.backoffice.schemas import (
    BlockReasonsOut,
    BlockSuggestionsOut,
    CreatedOut,
    MessageOut,
)

reasons_router = APIRouter(prefix="/block-reasons")
suggestions_router = APIRouter(prefix="/block-suggestions")
Blocker = Annotated[User, Depends(staff_required(*BLOCK_ROLES))]
Superuser = Annotated[User, Depends(superuser_required)]


class BlockReasonIn(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="The office's word.")
    message_uz: str = Field("", max_length=1000, description="What the account reads.")
    message_ru: str = Field("", max_length=1000)
    message_en: str = Field("", max_length=1000)
    position: int = Field(0, ge=0, le=1000)


class SuggestionBlockIn(BaseModel):
    reason_id: uuid.UUID | None = Field(
        None, description="Empty keeps the suggestion's own reason."
    )
    shown_to_user: bool = False
    note: str = Field("", max_length=500)


class DismissIn(BaseModel):
    note: str = Field(min_length=1, max_length=500, description="Why it may stay.")


def reason_out(row: BlockReason) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "message_uz": row.message_uz,
        "message_ru": row.message_ru,
        "message_en": row.message_en,
        "position": row.position,
        "is_archived": row.is_archived,
        "is_system": row.code is not None,
    }


def _reason(db: Db, reason_id: uuid.UUID) -> BlockReason:
    found = db.get(BlockReason, reason_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return found


@reasons_router.get("", responses={200: {"model": BlockReasonsOut}})
def block_reasons(db: Db, user: Blocker) -> dict[str, Any]:
    """The list to block with; archived ones only for the superuser, who
    keeps the list."""
    query = select(BlockReason).order_by(BlockReason.position, BlockReason.name)
    if not user.is_superuser:
        query = query.where(BlockReason.is_archived.is_(False))
    return {
        "rows": [reason_out(row) for row in db.scalars(query)],
        "may_edit": user.is_superuser,
    }


@reasons_router.post("", status_code=201, responses={201: {"model": CreatedOut}})
def add_block_reason(body: BlockReasonIn, db: Db, _: Superuser) -> dict[str, Any]:
    row = BlockReason(**_cleaned(db, body))
    db.add(row)
    db.commit()
    return {"message": "Sabab qo'shildi.", "id": str(row.id)}


@reasons_router.put("/{reason_id}", responses={200: {"model": MessageOut}})
def edit_block_reason(
    reason_id: uuid.UUID, body: BlockReasonIn, db: Db, _: Superuser
) -> dict[str, Any]:
    row = _reason(db, reason_id)
    for key, value in _cleaned(db, body, keep=row).items():
        setattr(row, key, value)
    db.commit()
    return {"message": "Sabab saqlandi."}


@reasons_router.post("/{reason_id}/archive", responses={200: {"model": MessageOut}})
def archive_block_reason(reason_id: uuid.UUID, db: Db, _: Superuser) -> dict[str, Any]:
    """Off the list to block with; blocks already made keep it."""
    row = _reason(db, reason_id)
    if row.code is not None:
        raise BlockReasonFixed
    row.is_archived = True
    db.commit()
    return {"message": "Sabab arxivlandi."}


@reasons_router.post("/{reason_id}/restore", responses={200: {"model": MessageOut}})
def restore_block_reason(reason_id: uuid.UUID, db: Db, _: Superuser) -> dict[str, Any]:
    row = _reason(db, reason_id)
    row.is_archived = False
    db.commit()
    return {"message": "Sabab qaytarildi."}


def _cleaned(
    db: Db, body: BlockReasonIn, *, keep: BlockReason | None = None
) -> dict[str, Any]:
    name = body.name.strip()
    same = select(BlockReason.id).where(func.lower(BlockReason.name) == name.lower())
    if keep is not None:
        same = same.where(BlockReason.id != keep.id)
    taken = db.scalar(same)
    if taken is not None:
        raise InputRefused({"name": "Bunday nomli sabab bor."})
    return {
        "name": name,
        "message_uz": body.message_uz.strip(),
        "message_ru": body.message_ru.strip(),
        "message_en": body.message_en.strip(),
        "position": body.position,
    }


# -- what the system asks Support to block --------------------------------------------


def _detail_out(db: Db, detail: dict[str, Any]) -> dict[str, Any]:
    held = detail.get("held_by") or ""
    holder = None
    try:
        holder = db.get(User, uuid.UUID(held)) if held else None
    except ValueError:
        holder = None
    return {
        "external_user_id": str(detail.get("external_user_id") or ""),
        "held_by": person_out(holder) if holder is not None else None,
    }


@suggestions_router.get("", responses={200: {"model": BlockSuggestionsOut}})
def block_suggestions(db: Db, _: Blocker) -> dict[str, Any]:
    """Open suggestions, the newest repeat first."""
    rows = list(
        db.scalars(
            select(BlockSuggestion)
            .options(
                joinedload(BlockSuggestion.owner), joinedload(BlockSuggestion.reason)
            )
            .where(BlockSuggestion.resolved_at.is_(None))
            .order_by(BlockSuggestion.last_at.desc())
        )
    )
    return {
        "rows": [
            {
                "id": str(row.id),
                "customer": {
                    **(person_out(row.owner) or {}),
                    "phone": row.owner.phone,
                },
                "reason": {"id": str(row.reason.id), "name": row.reason.name},
                "times": row.times,
                "first_at": row.created_at,
                "last_at": row.last_at,
                "detail": _detail_out(db, row.detail or {}),
            }
            for row in rows
        ],
        "total": len(rows),
    }


def _open_suggestion(db: Db, suggestion_id: uuid.UUID) -> BlockSuggestion:
    found = db.get(BlockSuggestion, suggestion_id)
    if found is None or found.resolved_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return found


@suggestions_router.post(
    "/{suggestion_id}/block", responses={200: {"model": MessageOut}}
)
def block_suggested(
    suggestion_id: uuid.UUID, body: SuggestionBlockIn, db: Db, actor: Blocker
) -> dict[str, Any]:
    """Block the account, under the suggestion's reason unless another is
    chosen; every open suggestion on it closes as blocked."""
    suggestion = _open_suggestion(db, suggestion_id)
    reason = (
        _reason(db, body.reason_id) if body.reason_id is not None else suggestion.reason
    )
    services.block_customer(
        db,
        customer=suggestion.owner,
        actor=actor,
        reason=reason,
        shown_to_user=body.shown_to_user,
        note=body.note,
        now=utcnow(),
    )
    db.commit()
    return {"message": "Akkaunt bloklandi."}


@suggestions_router.post(
    "/{suggestion_id}/dismiss", responses={200: {"model": MessageOut}}
)
def dismiss_suggested(
    suggestion_id: uuid.UUID, body: DismissIn, db: Db, actor: Blocker
) -> dict[str, Any]:
    """Let the account be; it comes back only if the system refuses it anew."""
    suggestion = _open_suggestion(db, suggestion_id)
    dismiss_suggestion(db, suggestion=suggestion, actor=actor, note=body.note)
    db.commit()
    return {"message": "Tavsiya yopildi."}
