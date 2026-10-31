"""The answers owners read when Meta refuses them, as JSON.

Every office role reads and corrects them: the first text is Claude's, and a
person who has seen the customer's screen is who can tell it is wrong.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import choices
from app.modules.backoffice.schemas import RefusalAnswerOut, RefusalAnswersOut
from app.modules.backoffice.selectors.refusals import (
    LINK_NAMES,
    TABS,
    operation_of,
    refusal_answer,
    refusal_answers,
)
from app.modules.backoffice.services.refusals import edit_refusal_answer
from app.modules.chat.constants import (
    REFUSAL_OFFICE_VERSION,
    REFUSAL_OPERATION_LABELS,
    REFUSAL_STALE_VERSIONS,
)
from app.modules.chat.models import RefusalAnswer

router = APIRouter(prefix="/refusals")
Staff = Annotated[User, Depends(staff_required(*Role))]


class RefusalAnswerIn(BaseModel):
    """The languages being changed; a field left out keeps its text."""

    answer_uz: str | None = Field(None, max_length=8000)
    answer_ru: str | None = Field(None, max_length=8000)
    answer_en: str | None = Field(None, max_length=8000)


def _out(row: RefusalAnswer) -> dict[str, Any]:
    operation = operation_of(row.key)
    return {
        "id": str(row.id),
        "key": row.key,
        "operation": operation,
        "operation_label": REFUSAL_OPERATION_LABELS[operation],
        "provider_title": row.provider_title,
        "provider_message": row.provider_message,
        "answer_uz": row.answer_uz,
        "answer_ru": row.answer_ru,
        "answer_en": row.answer_en,
        "written_by": "office"
        if row.prompt_version == REFUSAL_OFFICE_VERSION
        else "ai",
        "held": row.held,
        "retired": row.prompt_version in REFUSAL_STALE_VERSIONS,
        "hits": row.hits,
        "created_at": row.created_at,
        "edited_at": row.edited_at,
    }


def _found(db: Db, answer_id: uuid.UUID) -> RefusalAnswer:
    row = refusal_answer(db, answer_id=answer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return row


@router.get("", responses={200: {"model": RefusalAnswersOut}})
def refusals(
    db: Db,
    user: Staff,
    tab: str = Query(
        "", description="`held`, `untranslated`, `retired`; empty is all."
    ),
    q: str = Query("", description="Key, Meta's words, or the answer's own words."),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Every kept answer, the most often met first."""
    page = refusal_answers(db, tab=tab, term=q, offset=offset)
    return {
        "tab": tab,
        "tabs": choices(TABS),
        "links": choices(LINK_NAMES),
        "rows": [_out(row) for row in page.rows],
        "held": page.held,
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
    }


@router.get("/{answer_id}", responses={200: {"model": RefusalAnswerOut}})
def refusal(answer_id: uuid.UUID, db: Db, user: Staff) -> dict[str, Any]:
    return _out(_found(db, answer_id))


@router.patch("/{answer_id}", responses={200: {"model": RefusalAnswerOut}})
def edit_refusal(
    answer_id: uuid.UUID, body: RefusalAnswerIn, db: Db, actor: Staff
) -> dict[str, Any]:
    """Save the office's words; the next owner reads them at once."""
    row = edit_refusal_answer(
        db,
        actor=actor,
        row=_found(db, answer_id),
        answers=body.model_dump(exclude_none=True),
        now=utcnow(),
    )
    db.commit()
    return _out(row)
