"""Threads, the part of one that travels with the next question, and the replies an answer offered."""

import uuid
from collections.abc import Iterable
from typing import Any, Final

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.chat.constants import (
    HISTORY_CHARS,
    HISTORY_TURNS,
    SIDEBAR_SESSIONS,
    ChatMessageStatus,
    ChatRole,
)
from app.modules.chat.models import ChatMessage, ChatSession
from app.modules.integrations.models import AdAccount, PageAccount

REPLY_KIND: Final = "reply"


def _uuid(raw: Any) -> uuid.UUID | None:
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _here(owner: User) -> Select[tuple[ChatSession]]:
    """The threads of the pair the cabinet is on, and the ones of no page."""
    page = aliased(PageAccount)
    account = aliased(AdAccount)
    return (
        select(ChatSession)
        .outerjoin(page, page.id == ChatSession.page_id)
        .outerjoin(account, account.id == ChatSession.ad_account_id)
        .where(
            ChatSession.owner_id == owner.id,
            or_(
                ChatSession.page_id.is_(None),
                and_(
                    page.is_current.is_(True),
                    or_(
                        ChatSession.ad_account_id.is_(None),
                        account.is_current.is_(True),
                    ),
                ),
            ),
        )
        .order_by(ChatSession.last_message_at.desc(), ChatSession.created_at.desc())
    )


def sessions_for(db: Session, *, owner: User) -> list[ChatSession]:
    """The sidebar's list, newest first and bounded."""
    return list(db.scalars(_here(owner).limit(SIDEBAR_SESSIONS)))


def newest_session(db: Session, *, owner: User) -> ChatSession | None:
    """The thread a question with no screen behind it belongs to."""
    return db.scalar(_here(owner).limit(1))


def session_for(db: Session, *, owner: User, pk: uuid.UUID | str) -> ChatSession | None:
    """One thread of this owner's, or nothing."""
    key = _uuid(pk)
    if key is None:
        return None
    return db.scalar(_here(owner).where(ChatSession.id == key))


def answer_of(db: Session, *, owner: User, message_id: str) -> str:
    """The finished answer in one row, or nothing."""
    key = _uuid(message_id) if message_id else None
    if key is None:
        return ""
    row = db.scalar(
        select(ChatMessage).where(
            ChatMessage.owner_id == owner.id,
            ChatMessage.id == key,
            ChatMessage.status == ChatMessageStatus.DONE,
        )
    )
    return row.text if row is not None else ""


def messages_in(db: Session, *, owner: User, session: ChatSession) -> list[ChatMessage]:
    """One thread, oldest first. What the screen draws."""
    return list(
        db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.owner_id == owner.id, ChatMessage.session_id == session.id
            )
            .order_by(ChatMessage.created_at)
        )
    )


def history(
    db: Session, *, owner: User, session: ChatSession
) -> tuple[tuple[str, str], ...]:
    """The last few finished turns, oldest first, within a character budget."""
    rows = db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.owner_id == owner.id,
            ChatMessage.session_id == session.id,
            ChatMessage.status == ChatMessageStatus.DONE,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_TURNS)
    )
    return tuple(reversed(_within_budget(list(rows))))


def _within_budget(rows: list[ChatMessage]) -> list[tuple[str, str]]:
    kept: list[tuple[str, str]] = []
    spent = 0
    for row in rows:
        text = _said(row)
        if kept and spent + len(text) > HISTORY_CHARS:
            break
        kept.append((row.role, text))
        spent += len(text)
    return kept


def _said(row: ChatMessage) -> str:
    """A turn as the model reads it back, with what it replied to in front."""
    quote = row.quote or {}
    if row.role != ChatRole.USER or not quote.get("title"):
        return row.text
    quoted = " - ".join(
        str(part)
        for part in (quote.get("title"), quote.get("target"), quote.get("body"))
        if part
    )
    return f'(replying to the waiting-list line "{quoted}")\n{row.text}'


def reply_items(replies: Iterable[str]) -> list[dict[str, str]]:
    """The replies as they are stored on the answer's row."""
    return [{"kind": REPLY_KIND, "label": label} for label in replies]


def replies_in(choices: Iterable[dict[str, Any]] | None) -> list[str]:
    """The reply labels in one row's stored list, in the order offered."""
    return [
        str(item.get("label", ""))
        for item in (choices or ())
        if item.get("kind") == REPLY_KIND and item.get("label")
    ]


def with_replies(messages: list[Any]) -> list[Any]:
    """The thread, with the last answer's replies attached and no others."""
    for message in messages:
        message.replies = []
    if messages:
        last = messages[-1]
        if last.role == ChatRole.ASSISTANT and last.status == ChatMessageStatus.DONE:
            last.replies = replies_in(last.choices)
    return messages


def _row(db: Session, owner: User, message_id: str) -> ChatMessage | None:
    key = _uuid(message_id)
    if key is None:
        return None
    return db.scalar(
        select(ChatMessage).where(
            ChatMessage.owner_id == owner.id, ChatMessage.id == key
        )
    )


def replies_on(db: Session, *, owner: User, message_id: str) -> list[str]:
    """What one finished answer offered as replies, read back off its row."""
    row = _row(db, owner, message_id)
    return replies_in(row.choices) if row is not None else []


def pressable_reply(db: Session, *, owner: User, message_id: str, index: int) -> str:
    """The words of one reply, if it can still be sent. Otherwise nothing."""
    row = _row(db, owner, message_id)
    if row is None or row.status != ChatMessageStatus.DONE:
        return ""
    labels = replies_in(row.choices)
    if not 0 <= index < len(labels):
        return ""
    later = db.scalar(
        select(ChatMessage.id)
        .where(
            ChatMessage.owner_id == owner.id,
            ChatMessage.session_id == row.session_id,
            ChatMessage.created_at > row.created_at,
        )
        .limit(1)
    )
    return "" if later is not None else labels[index]


__all__ = [
    "REPLY_KIND",
    "answer_of",
    "history",
    "messages_in",
    "newest_session",
    "pressable_reply",
    "replies_in",
    "replies_on",
    "reply_items",
    "session_for",
    "sessions_for",
    "with_replies",
]
