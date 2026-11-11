"""Support inside the one chat: a person's replies in the same thread.

The support chat keeps its own tables, queue, Telegram relay and office
screens - nothing about how Support works changes. What changes is where the
client sees it: a message between the client and Support is also a row of an
assistant thread.

How a row gets there
    The support chat fires ``MESSAGE_STORED`` inside the transaction that
    stores a message (``supportchat/services/_store.py``), and ``show``
    writes the thread's row in that same commit - whoever wrote it and from
    wherever: this chat, the office, the Telegram bots, the old support
    screen. ``assistant_messages.support_message_id`` is unique, so nothing
    shows twice.

For whom
    Only a client who has talked to Support from this chat has a thread to
    show it in. Everybody else's support chat is left alone until they open
    this chat, when ``ensure_thread`` brings their earlier support chat in.

What a row shows
    Its words are kept for the model to read back. Files, a voice, a
    sticker, "edited" and the ticks are read from the support message each
    time the thread is drawn (``views``), so they are never stale.

A client with no plan still reaches a person: nothing here asks for one.
"""

import logging
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    IMPORT_ROWS,
    REPLY_WINDOW,
    SESSION_TTL_DAYS,
    SUPPORT_TITLE,
    TEAM,
    Author,
    ButtonKind,
    ButtonState,
    MessageStatus,
    Mode,
)
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.assistant.selectors.threads import visible
from app.modules.supportchat.constants import CLIENT
from core.chat.markdown import render

logger = logging.getLogger(__name__)

_HINT: Final = "assistant_support_hint"


@dataclass(frozen=True, slots=True)
class _Hint:
    """What this chat tells ``show`` about a message it is sending itself."""

    thread_id: uuid.UUID | None
    # False for a ticket: its words are in the thread already, as the
    # question and the assistant's answer.
    as_row: bool


@dataclass(frozen=True, slots=True)
class Written:
    session: AssistantSession
    message: AssistantMessage
    support_message: Any


@dataclass(frozen=True, slots=True)
class SupportState:
    """What the chat screen knows about Support for this client."""

    thread_id: str
    unread: bool
    waiting: bool


@contextmanager
def sending_from(
    db: Session, *, thread: AssistantSession | None, as_row: bool = True
) -> Iterator[None]:
    """While this chat itself sends to Support: which thread it is from."""
    db.info[_HINT] = _Hint(thread_id=thread.id if thread else None, as_row=as_row)
    try:
        yield
    finally:
        db.info.pop(_HINT, None)


def write_to_support(
    db: Session,
    *,
    owner: User,
    session: AssistantSession | None,
    draft: Any,
    now: datetime,
    send_key: str = "",
) -> Written:
    """The client's words to a person, from the chat. The support chat
    stores them (its rate limit, files, audit and Telegram copy all apply)
    and ``show`` writes the thread's row in the same commit."""
    from app.modules.supportchat.services import send_to_support

    thread = session or support_thread(db, owner=owner)
    with sending_from(db, thread=thread):
        sent = send_to_support(db, owner=owner, draft=draft, now=now, send_key=send_key)
    row = row_of(db, support_message_id=sent.id)
    if row is None:
        # ``on_stored`` guards itself and never fails the message: write the
        # row now rather than leave words the client cannot see.
        show(db, message=sent, now=now, thread_id=thread.id if thread else None)
        db.commit()
        row = row_of(db, support_message_id=sent.id)
    if row is None:  # pragma: no cover - two writes failed for one message
        raise LookupError("support message has no assistant row")
    found = db.get(AssistantSession, row.session_id)
    assert found is not None
    return Written(session=found, message=row, support_message=sent)


def on_stored(db: Session, *, message: Any, now: datetime) -> None:
    """The support chat stored a message: show it in the client's chat.
    Inside the message's own transaction, behind a savepoint - a failure
    here costs the copy, never the message."""
    hint: _Hint | None = db.info.get(_HINT)
    try:
        with db.begin_nested():
            if hint is not None and not hint.as_row:
                _touch(db, thread_id=hint.thread_id, now=now)
                return
            if hint is None and not _uses_this_chat(db, owner_id=message.owner_id):
                return
            show(
                db,
                message=message,
                now=now,
                thread_id=hint.thread_id if hint is not None else None,
            )
    except Exception:
        logger.exception(
            "assistant_support_show_failed", extra={"message_id": str(message.id)}
        )


def on_changed(db: Session, *, message: Any) -> None:
    """New words on a support message, or it was taken back: the thread's
    row follows. A taken-back message leaves the thread."""
    try:
        with db.begin_nested():
            if message.deleted_at is not None:
                db.execute(
                    delete(AssistantMessage).where(
                        AssistantMessage.support_message_id == message.id
                    )
                )
                return
            text = _words(db, message)
            db.execute(
                update(AssistantMessage)
                .where(AssistantMessage.support_message_id == message.id)
                .values(text=text, html=render(text))
            )
    except Exception:
        logger.exception(
            "assistant_support_change_failed", extra={"message_id": str(message.id)}
        )


def show(
    db: Session,
    *,
    message: Any,
    now: datetime,
    thread_id: uuid.UUID | None = None,
) -> bool:
    """Write the thread's row for one support message. Returns whether a row
    was written: a message already shown or taken back writes nothing."""
    if message.deleted_at is not None:
        return False
    if row_of(db, support_message_id=message.id) is not None:
        return False
    owner = db.get(User, message.owner_id)
    if owner is None:
        return False
    thread = _thread(db, owner=owner, thread_id=thread_id)
    if thread is None:
        thread = _open_thread(db, owner=owner, now=now, skip=message.id)
    db.add(_row(db, thread=thread, message=message))
    thread.support_at = now
    thread.last_message_at = now
    db.flush()
    logger.info(
        "assistant_support_shown",
        extra={"message_id": str(message.id), "thread_id": str(thread.id)},
    )
    return True


def row_of(db: Session, *, support_message_id: Any) -> AssistantMessage | None:
    """The thread row that is this support message."""
    return db.scalar(
        select(AssistantMessage).where(
            AssistantMessage.support_message_id == support_message_id
        )
    )


def support_thread(db: Session, *, owner: User) -> AssistantSession | None:
    """The thread Support was last part of, among the ones the cabinet shows
    now. A thread of another page is not it: the reply would be unseen."""
    return db.scalar(
        visible(owner)
        .where(AssistantSession.support_at.is_not(None))
        .order_by(None)
        .order_by(AssistantSession.support_at.desc())
        .limit(1)
    )


def ensure_thread(
    db: Session, *, owner: User, now: datetime
) -> AssistantSession | None:
    """A client who talked to Support before this chat: bring that chat into
    a thread the first time they open this one. Nothing for a client with
    no support chat, or one too old to keep."""
    from app.modules.supportchat.selectors import chat_of

    found = support_thread(db, owner=owner)
    if found is not None:
        return found
    conversation = chat_of(db, owner=owner)
    if conversation is None or not _recent(conversation.last_message_at, now=now):
        return None
    if not _earlier(db, owner=owner, skip=None, limit=1):
        return None
    try:
        thread = _open_thread(db, owner=owner, now=now, skip=None)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("assistant_support_import_failed")
        return None
    return thread


def state_for(db: Session, *, owner: User) -> SupportState:
    """The badge and the door: is there a reply unread, is a person asked."""
    from app.modules.supportchat.selectors import chat_of, is_unread, is_waiting

    conversation = chat_of(db, owner=owner)
    thread = support_thread(db, owner=owner)
    return SupportState(
        thread_id=str(thread.id) if thread is not None else "",
        unread=conversation is not None and is_unread(conversation=conversation),
        waiting=conversation is not None and is_waiting(conversation=conversation),
    )


def thread_mode(
    db: Session,
    *,
    owner: User,
    thread: AssistantSession | None,
    messages: Sequence[Any],
    entitled: bool,
    now: datetime,
) -> str:
    """``support`` while this thread is with a person, ``ai`` otherwise.

    With a person: the client's last words went to Support and wait for an
    answer, or a person answered within ``REPLY_WINDOW``. Anything after
    that - the assistant answered since, the office closed the question, a
    day went by - gives the composer back to the assistant. A client with
    no plan has only the person to talk to. The page may switch it.
    """
    if not entitled:
        return Mode.SUPPORT
    last = next(
        (row for row in reversed(messages) if row.status != MessageStatus.FAILED),
        None,
    )
    if thread is None or thread.support_at is None or last is None:
        return Mode.AI
    if last.author == Author.STAFF:
        fresh = now - last.created_at <= REPLY_WINDOW
        return Mode.SUPPORT if fresh else Mode.AI
    if is_to_support(last) or ticket_sent(last):
        return Mode.SUPPORT if _waiting(db, owner=owner) else Mode.AI
    return Mode.AI


def read(db: Session, *, owner: User, thread: AssistantSession | None) -> None:
    """The client has a person's reply in front of them: the support chat is
    read - the badge goes, the office's ticks turn, and the next reply is
    announced to their phone again. Only a thread that holds a reply they
    had not seen counts."""
    from app.common.db import utcnow
    from app.modules.supportchat.live import broadcast_read
    from app.modules.supportchat.selectors import chat_of, is_unread
    from app.modules.supportchat.services import mark_read

    if thread is None or thread.support_at is None:
        return
    conversation = chat_of(db, owner=owner)
    if conversation is None or not is_unread(conversation=conversation):
        return
    seen = conversation.client_read_at
    unseen = db.scalar(
        select(AssistantMessage.id)
        .where(
            AssistantMessage.owner_id == owner.id,
            AssistantMessage.session_id == thread.id,
            AssistantMessage.author == Author.STAFF,
            *([AssistantMessage.created_at > seen] if seen is not None else []),
        )
        .limit(1)
    )
    if unseen is None:
        return
    now = utcnow()
    if mark_read(db, conversation=conversation, reader=owner, now=now):
        broadcast_read(owner_id=owner.id, side=CLIENT, at=now)


def views(
    db: Session, *, owner: User, messages: Sequence[Any], now: datetime
) -> dict[uuid.UUID, dict[str, Any]]:
    """For each thread row that is a support message: how the support chat
    draws it for the client - files with their addresses, a voice, a
    sticker, edited, read, and whether it may still be changed."""
    from app.modules.supportchat import selectors
    from app.modules.supportchat.models import SupportMessage

    linked = {
        row.support_message_id: row.id for row in messages if row.support_message_id
    }
    if not linked:
        return {}
    conversation = selectors.chat_of(db, owner=owner)
    if conversation is None:
        return {}
    found = list(
        db.scalars(
            select(SupportMessage).where(
                SupportMessage.id.in_(linked), SupportMessage.owner_id == owner.id
            )
        )
    )
    drawn = selectors.drawn(db, found)
    return {
        linked[message.id]: selectors.message_view(
            message, drawn=drawn, conversation=conversation, viewer=CLIENT, now=now
        )
        for message in found
    }


def support_path(db: Session, *, owner: User) -> str:
    """Where the page sends a client who came for Support's reply."""
    thread = support_thread(db, owner=owner)
    return str(thread.id) if thread is not None else ""


def is_to_support(row: Any) -> bool:
    """A client's row whose words went to a person, not to the assistant."""
    return row.author == Author.USER and row.support_message_id is not None


def ticket_sent(row: Any) -> bool:
    """An answer whose ticket button was pressed."""
    return row.author == Author.AI and any(
        isinstance(item, dict)
        and item.get("kind") == ButtonKind.TICKET
        and item.get("state") not in (ButtonState.OPEN, ButtonState.DISMISSED)
        for item in (row.buttons or ())
    )


def _uses_this_chat(db: Session, *, owner_id: Any) -> bool:
    """Whether this client has ever had Support in a thread of this chat."""
    return (
        db.scalar(
            select(AssistantSession.id)
            .where(
                AssistantSession.owner_id == owner_id,
                AssistantSession.support_at.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def _waiting(db: Session, *, owner: User) -> bool:
    from app.modules.supportchat.selectors import chat_of, is_waiting

    conversation = chat_of(db, owner=owner)
    return conversation is not None and is_waiting(conversation=conversation)


def _recent(moment: datetime | None, *, now: datetime) -> bool:
    return moment is not None and now - moment < timedelta(days=SESSION_TTL_DAYS)


def _thread(
    db: Session, *, owner: User, thread_id: uuid.UUID | None
) -> AssistantSession | None:
    if thread_id is not None:
        found = db.get(AssistantSession, thread_id)
        if found is not None and found.owner_id == owner.id:
            return found
    return support_thread(db, owner=owner)


def _touch(db: Session, *, thread_id: uuid.UUID | None, now: datetime) -> None:
    """Support is part of this thread from now, with no row of its own."""
    if thread_id is None:
        return
    db.execute(
        update(AssistantSession)
        .where(AssistantSession.id == thread_id)
        .values(support_at=now)
    )


def _earlier(
    db: Session, *, owner: User, skip: uuid.UUID | None, limit: int
) -> list[Any]:
    """The client's support messages no thread shows yet, newest first."""
    from app.modules.supportchat.models import SupportMessage

    shown = select(AssistantMessage.support_message_id).where(
        AssistantMessage.owner_id == owner.id,
        AssistantMessage.support_message_id.is_not(None),
    )
    return list(
        db.scalars(
            select(SupportMessage)
            .where(
                SupportMessage.owner_id == owner.id,
                SupportMessage.deleted_at.is_(None),
                SupportMessage.id.not_in(shown),
                *([SupportMessage.id != skip] if skip is not None else []),
            )
            .order_by(SupportMessage.created_at.desc(), SupportMessage.id.desc())
            .limit(limit)
        )
    )


def _open_thread(
    db: Session, *, owner: User, now: datetime, skip: uuid.UUID | None
) -> AssistantSession:
    """A thread of no page - shown whichever page the cabinet is on - with
    the client's earlier support chat in it, oldest first. ``skip`` is the
    message being shown right now, which its caller writes."""
    thread = AssistantSession(owner_id=owner.id, title=SUPPORT_TITLE)
    db.add(thread)
    db.flush()
    earlier = _earlier(db, owner=owner, skip=skip, limit=IMPORT_ROWS)
    for message in reversed(earlier):
        db.add(_row(db, thread=thread, message=message))
    if earlier:
        thread.support_at = now
        thread.last_message_at = earlier[0].created_at
    db.flush()
    return thread


def _row(db: Session, *, thread: AssistantSession, message: Any) -> AssistantMessage:
    from app.modules.supportchat.rules import side_of

    from_client = side_of(message) == CLIENT
    text = _words(db, message)
    return AssistantMessage(
        owner_id=message.owner_id,
        session_id=thread.id,
        author=Author.USER if from_client else Author.STAFF,
        text=text,
        html=render(text),
        status=MessageStatus.DONE,
        buttons=[],
        replies=[],
        meta={} if from_client else {"author": _author(db, message)},
        support_message_id=message.id,
        created_at=message.created_at,
    )


def _words(db: Session, message: Any) -> str:
    """The message as a line of words - what the model reads back, and what
    a page that cannot draw files shows."""
    from app.modules.supportchat.models import SupportAttachment
    from app.modules.supportchat.preview import files_label, preview_text

    files = list(
        db.scalars(
            select(SupportAttachment)
            .where(SupportAttachment.message_id == message.id)
            .order_by(SupportAttachment.position)
        )
    )
    words = preview_text(message, files)
    label = files_label(message=message, files=files).removeprefix("Fayl: ")
    if message.body and label:
        return f"{words}\n📎 {label}"
    if label and not message.body and words.endswith(label):
        return f"📎 {label}"
    return words or "📎 Fayl"


def _author(db: Session, message: Any) -> str:
    """The first name of whoever in Support wrote it, or the team's."""
    sender = db.get(User, message.sender_id) if message.sender_id else None
    if sender is None:
        return TEAM
    return ((sender.full_name or "").split() or [TEAM])[0]


__all__ = [
    "SupportState",
    "Written",
    "ensure_thread",
    "is_to_support",
    "on_changed",
    "on_stored",
    "read",
    "row_of",
    "sending_from",
    "show",
    "state_for",
    "support_path",
    "support_thread",
    "thread_mode",
    "ticket_sent",
    "views",
    "write_to_support",
]
