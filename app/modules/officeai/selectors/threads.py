"""An office person's own threads, and what the model is shown of one."""

import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.officeai.constants import (
    HISTORY_CHARS,
    HISTORY_TURNS,
    PAGE_MESSAGES,
    SIDEBAR_THREADS,
    Author,
    MessageStatus,
)
from app.modules.officeai.models import OfficeAiMessage, OfficeAiThread


def as_uuid(raw: Any) -> uuid.UUID | None:
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def threads_for(db: Session, *, staff: User) -> list[OfficeAiThread]:
    return list(
        db.scalars(
            select(OfficeAiThread)
            .where(OfficeAiThread.staff_id == staff.id)
            .order_by(
                OfficeAiThread.last_message_at.desc().nulls_last(),
                OfficeAiThread.created_at.desc(),
            )
            .limit(SIDEBAR_THREADS)
        )
    )


def thread_for(db: Session, *, staff: User, pk: Any) -> OfficeAiThread | None:
    """One of this person's threads; somebody else's is not found."""
    key = as_uuid(pk)
    if key is None:
        return None
    return db.scalar(
        select(OfficeAiThread).where(
            OfficeAiThread.id == key, OfficeAiThread.staff_id == staff.id
        )
    )


def message_for(db: Session, *, staff: User, pk: Any) -> OfficeAiMessage | None:
    key = as_uuid(pk)
    if key is None:
        return None
    return db.scalar(
        select(OfficeAiMessage).where(
            OfficeAiMessage.id == key, OfficeAiMessage.staff_id == staff.id
        )
    )


def messages_page(
    db: Session,
    *,
    thread: OfficeAiThread,
    before: OfficeAiMessage | None = None,
    limit: int = PAGE_MESSAGES,
) -> tuple[list[OfficeAiMessage], bool]:
    """The newest ``limit`` rows - or those before ``before`` - oldest
    first, and whether older ones are left."""
    query = select(OfficeAiMessage).where(OfficeAiMessage.thread_id == thread.id)
    if before is not None:
        query = query.where(
            or_(
                OfficeAiMessage.created_at < before.created_at,
                and_(
                    OfficeAiMessage.created_at == before.created_at,
                    OfficeAiMessage.id < before.id,
                ),
            )
        )
    rows = list(
        db.scalars(
            query.order_by(
                OfficeAiMessage.created_at.desc(), OfficeAiMessage.id.desc()
            ).limit(limit + 1)
        )
    )
    return list(reversed(rows[:limit])), len(rows) > limit


def history(db: Session, *, thread: OfficeAiThread) -> tuple[tuple[str, str], ...]:
    """The last finished turns, as the model reads them: the person's words
    and the answers, taking turns, starting with the person."""
    rows = list(
        db.scalars(
            select(OfficeAiMessage)
            .where(
                OfficeAiMessage.thread_id == thread.id,
                OfficeAiMessage.status == MessageStatus.DONE,
                OfficeAiMessage.text != "",
            )
            .order_by(OfficeAiMessage.created_at.desc(), OfficeAiMessage.id.desc())
            .limit(HISTORY_TURNS * 2)
        )
    )
    said: list[tuple[str, str]] = []
    for row in reversed(rows):
        role = "assistant" if row.author == Author.AI else "user"
        if said and said[-1][0] == role:
            said[-1] = (role, f"{said[-1][1]}\n\n{row.text}")
        else:
            said.append((role, row.text))
    while said and said[0][0] != "user":
        said.pop(0)
    # The question that follows is the person's: the history ends on an answer.
    if said and said[-1][0] == "user":
        said.pop()
    kept: list[tuple[str, str]] = []
    total = 0
    for role, text in reversed(said):
        total += len(text)
        if total > HISTORY_CHARS:
            break
        kept.append((role, text))
    kept.reverse()
    while kept and kept[0][0] != "user":
        kept.pop(0)
    return tuple(kept)


__all__ = [
    "as_uuid",
    "history",
    "message_for",
    "messages_page",
    "thread_for",
    "threads_for",
]
