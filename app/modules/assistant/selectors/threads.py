"""Reading the one chat's threads: the rail, one thread, and what the model
is shown of what was said before."""

import uuid
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    HISTORY_CHARS,
    HISTORY_TURNS,
    PAGE_MESSAGES,
    SIDEBAR_SESSIONS,
    Author,
    MessageStatus,
)
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.integrations.models import AdAccount, PageAccount

STAFF_MARK = "[Support xodimi yozdi]"
TO_STAFF_MARK = "[Mijoz Support xodimiga yozdi]"


def as_uuid(raw: Any) -> uuid.UUID | None:
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def visible(owner: User) -> Select[Any]:
    """The threads of the page the cabinet is on, and the ones of no page,
    newest first."""
    page = aliased(PageAccount)
    account = aliased(AdAccount)
    return (
        select(AssistantSession)
        .outerjoin(page, page.id == AssistantSession.page_id)
        .outerjoin(account, account.id == AssistantSession.ad_account_id)
        .where(
            AssistantSession.owner_id == owner.id,
            or_(
                AssistantSession.page_id.is_(None),
                and_(
                    page.is_current.is_(True),
                    or_(
                        AssistantSession.ad_account_id.is_(None),
                        account.is_current.is_(True),
                    ),
                ),
            ),
        )
        .order_by(
            AssistantSession.last_message_at.desc().nulls_last(),
            AssistantSession.created_at.desc(),
        )
    )


def sessions_for(db: Session, *, owner: User) -> list[AssistantSession]:
    return list(db.scalars(visible(owner).limit(SIDEBAR_SESSIONS)))


def session_for(
    db: Session, *, owner: User, pk: uuid.UUID | str
) -> AssistantSession | None:
    """One of this owner's threads the cabinet shows now, or nothing."""
    key = as_uuid(pk)
    if key is None:
        return None
    return db.scalar(visible(owner).where(AssistantSession.id == key))


def message_for(
    db: Session, *, owner: User, pk: uuid.UUID | str, lock: bool = False
) -> AssistantMessage | None:
    key = as_uuid(pk)
    if key is None:
        return None
    query = select(AssistantMessage).where(
        AssistantMessage.owner_id == owner.id, AssistantMessage.id == key
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def messages_page(
    db: Session,
    *,
    owner: User,
    session: AssistantSession,
    before: AssistantMessage | None = None,
    limit: int = PAGE_MESSAGES,
) -> tuple[list[AssistantMessage], bool]:
    """The newest ``limit`` rows of a thread - or the ones written before
    ``before`` - oldest first, and whether older ones are left."""
    query = select(AssistantMessage).where(
        AssistantMessage.owner_id == owner.id,
        AssistantMessage.session_id == session.id,
    )
    if before is not None:
        query = query.where(
            or_(
                AssistantMessage.created_at < before.created_at,
                and_(
                    AssistantMessage.created_at == before.created_at,
                    AssistantMessage.id < before.id,
                ),
            )
        )
    rows = list(
        db.scalars(
            query.order_by(
                AssistantMessage.created_at.desc(), AssistantMessage.id.desc()
            ).limit(limit + 1)
        )
    )
    return list(reversed(rows[:limit])), len(rows) > limit


def history(
    db: Session, *, owner: User, session: AssistantSession
) -> tuple[tuple[str, str], ...]:
    """The last few finished turns as the model reads them: its own answers
    and a person's replies on one side, the client's words on the other.

    The provider wants the two sides to take turns and the client to speak
    first, so neighbours on one side are joined and anything before the
    client's first words is left out."""
    rows = list(
        db.scalars(
            select(AssistantMessage)
            .where(
                AssistantMessage.owner_id == owner.id,
                AssistantMessage.session_id == session.id,
                AssistantMessage.status == MessageStatus.DONE,
                AssistantMessage.text != "",
            )
            .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
            .limit(HISTORY_TURNS)
        )
    )
    kept: list[tuple[str, str]] = []
    spent = 0
    for row in rows:
        role, text = as_model_reads(row)
        if kept and spent + len(text) > HISTORY_CHARS:
            break
        kept.append((role, text))
        spent += len(text)
    return turns(tuple(reversed(kept)))


def as_model_reads(row: Any) -> tuple[str, str]:
    """One row as a turn: who the provider is told spoke, and the words."""
    if row.author == Author.STAFF:
        return "assistant", f"{STAFF_MARK}\n{row.text}"
    if row.author == Author.AI:
        return "assistant", row.text
    quoted = (row.meta or {}).get("quote") or {}
    words = row.text
    if quoted.get("title"):
        about = " - ".join(
            str(part)
            for part in (quoted.get("title"), quoted.get("target"), quoted.get("body"))
            if part
        )
        words = f'(replying to the waiting-list line "{about}")\n{words}'
    if row.support_message_id is not None:
        words = f"{TO_STAFF_MARK}\n{words}"
    return "user", words


def turns(said: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """Take turns, the client first."""
    joined: list[tuple[str, str]] = []
    for role, text in said:
        if not joined and role != "user":
            continue
        if joined and joined[-1][0] == role:
            joined[-1] = (role, f"{joined[-1][1]}\n\n{text}")
        else:
            joined.append((role, text))
    return tuple(joined)


__all__ = [
    "STAFF_MARK",
    "TO_STAFF_MARK",
    "as_model_reads",
    "as_uuid",
    "history",
    "message_for",
    "messages_page",
    "session_for",
    "sessions_for",
    "turns",
    "visible",
]
