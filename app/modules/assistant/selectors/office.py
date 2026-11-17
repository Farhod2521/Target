"""The client's chat with the assistant, as the office reads it.

Support sees the client's one chat whole: their questions and the
assistant's answers beside the support chat's own messages. The rows that
are support messages (``support_message_id``) are left out here - the
office draws those from the support chat itself, with their files and
ticks. Every thread of the client counts, whichever page it belongs to.
"""

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assistant.constants import Author
from app.modules.assistant.models import AssistantMessage, AssistantSession

# Rows read for one screen of the office's chat, the newest.
OFFICE_ROWS: Final = 200


def _offered(buttons: Any) -> list[dict[str, str]]:
    """What the answer offered under it, and where each has got to."""
    return [
        {
            "kind": str(item.get("kind", "")),
            "label": str(item.get("label", "")),
            "summary": str(item.get("summary", "")),
            "state": str(item.get("state", "")),
        }
        for item in buttons or ()
        if isinstance(item, dict)
    ]


def assistant_rows(
    db: Session,
    *,
    owner_id: UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = OFFICE_ROWS,
) -> list[dict[str, Any]]:
    """The client's questions and the assistant's answers from ``since``
    up to ``until`` (open on a side with none), oldest first - at most
    ``limit``, the newest ones."""
    query = (
        select(AssistantMessage, AssistantSession.title)
        .join(AssistantSession, AssistantSession.id == AssistantMessage.session_id)
        .where(
            AssistantMessage.owner_id == owner_id,
            AssistantMessage.support_message_id.is_(None),
            AssistantMessage.author.in_((str(Author.USER), str(Author.AI))),
        )
        .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
        .limit(limit)
    )
    if since is not None:
        query = query.where(AssistantMessage.created_at >= since)
    if until is not None:
        query = query.where(AssistantMessage.created_at < until)
    rows = list(db.execute(query))
    return [
        {
            "id": str(row.id),
            "thread_id": str(row.session_id),
            "thread_title": title or "",
            "author": row.author,
            "text": row.text,
            "status": row.status,
            "stopped": bool((row.meta or {}).get("stopped")),
            "offered": _offered(row.buttons) if row.author == Author.AI else [],
            "lessons": [
                str(item.get("title", ""))
                for item in (row.meta or {}).get("lessons", ())
                if isinstance(item, dict)
            ],
            "created_at": row.created_at,
        }
        for row, title in reversed(rows)
    ]


__all__ = ["OFFICE_ROWS", "assistant_rows"]
