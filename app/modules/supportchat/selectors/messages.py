"""Reading the messages inside one chat."""

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.modules.accounts.models import User
from app.modules.supportchat.constants import MESSAGE_PAGE_SIZE
from app.modules.supportchat.models import (
    SupportAttachment,
    SupportConversation,
    SupportMessage,
)
from app.modules.supportchat.selectors.conversations import coerce

M = SupportMessage
A = SupportAttachment


@dataclass(frozen=True, slots=True)
class Drawn:
    """Messages with everything drawing them reads: their files, the quoted
    messages and the quotes' files, keyed by message id."""

    messages: list[SupportMessage]
    files: dict[uuid.UUID, list[SupportAttachment]]
    quotes: dict[uuid.UUID, SupportMessage]


@dataclass(frozen=True, slots=True)
class MessagePage:
    drawn: Drawn
    number: int
    pages: int
    count: int

    @property
    def has_previous(self) -> bool:
        return self.number > 1

    @property
    def has_next(self) -> bool:
        return self.number < self.pages


def _drawn_query() -> Select[tuple[SupportMessage]]:
    return select(M).options(selectinload(M.sender))


def drawn(db: Session, messages: Sequence[SupportMessage]) -> Drawn:
    """The rows, the messages they quote, and both one's files - three
    queries whatever the page holds.

    Quotes are read by ``reply_to_id`` rather than through the model's
    ``reply_to``: a self-referencing relationship without ``remote_side``
    reads the other direction.
    """
    rows = list(messages)
    quoted = {row.reply_to_id for row in rows if row.reply_to_id is not None}
    quotes = (
        {row.id: row for row in db.scalars(_drawn_query().where(M.id.in_(quoted)))}
        if quoted
        else {}
    )
    ids = {row.id for row in rows} | set(quotes)
    files: dict[uuid.UUID, list[SupportAttachment]] = defaultdict(list)
    if ids:
        for item in db.scalars(
            select(A).where(A.message_id.in_(ids)).order_by(A.message_id, A.position)
        ):
            files[item.message_id].append(item)
    return Drawn(messages=rows, files=dict(files), quotes=quotes)


def _page_number(raw: str | None, pages: int) -> int:
    """Django's ``Paginator.get_page``: not a number is the first page, out
    of range is the last."""
    if raw is None or raw == "":
        return pages
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return 1
    if number < 1 or number > pages:
        return pages
    return number


def messages_page(
    db: Session,
    *,
    owner: User,
    conversation: SupportConversation | None,
    page: str | None = None,
) -> MessagePage:
    """One page of this client's chat, the newest unless another was asked
    for. No chat at all reads as an empty one."""
    if conversation is None:
        return MessagePage(
            drawn=Drawn(messages=[], files={}, quotes={}), number=1, pages=1, count=0
        )
    scope = (M.owner_id == owner.id, M.conversation_id == conversation.id)
    count = int(db.scalar(select(func.count()).select_from(M).where(*scope)) or 0)
    pages = max(1, math.ceil(count / MESSAGE_PAGE_SIZE))
    number = _page_number(page, pages)
    rows = db.scalars(
        _drawn_query()
        .where(*scope)
        .order_by(M.created_at, M.id)
        .offset((number - 1) * MESSAGE_PAGE_SIZE)
        .limit(MESSAGE_PAGE_SIZE)
    ).all()
    return MessagePage(drawn=drawn(db, rows), number=number, pages=pages, count=count)


def changed_since(
    db: Session,
    *,
    owner: User,
    conversation: SupportConversation,
    since: datetime | None,
) -> Drawn:
    """Messages written or changed at or after ``since``; with no moment,
    the newest page."""
    scope = (M.owner_id == owner.id, M.conversation_id == conversation.id)
    if since is None:
        newest = db.scalars(
            _drawn_query()
            .where(*scope)
            .order_by(M.created_at.desc(), M.id.desc())
            .limit(MESSAGE_PAGE_SIZE)
        ).all()
        return drawn(db, list(reversed(newest)))
    rows = db.scalars(
        _drawn_query().where(*scope, M.updated_at >= since).order_by(M.created_at, M.id)
    ).all()
    return drawn(db, rows)


def last_change(
    db: Session, *, owner: User, conversation: SupportConversation
) -> datetime | None:
    """The newest moment any message in this chat was written or changed."""
    return db.scalar(
        select(func.max(M.updated_at)).where(
            M.owner_id == owner.id, M.conversation_id == conversation.id
        )
    )


def message_in_chat(
    db: Session, *, owner_id: uuid.UUID, message_id: uuid.UUID | str
) -> SupportMessage | None:
    """One message of this client's chat, for a socket to draw; anything
    else reads as missing."""
    ident = coerce(message_id)
    if ident is None:
        return None
    return db.scalar(_drawn_query().where(M.id == ident, M.owner_id == owner_id))


def staff_messages_in(db: Session, *, conversation: SupportConversation) -> Drawn:
    """Any client's messages in one chat. Cross-tenant by design - the
    caller has already established the office role."""
    rows = db.scalars(
        _drawn_query()
        .where(M.conversation_id == conversation.id)
        .order_by(M.created_at, M.id)
    ).all()
    return drawn(db, rows)


def message_for_download(
    db: Session, *, owner: User, message_id: uuid.UUID | str
) -> SupportMessage | None:
    """One of this client's messages that carries a file, or ``None``."""
    ident = coerce(message_id)
    if ident is None:
        return None
    return db.scalar(
        select(M).where(M.id == ident, M.owner_id == owner.id, M.attachment != "")
    )


def staff_message_for_download(
    db: Session, *, message_id: uuid.UUID | str
) -> SupportMessage | None:
    """Any client's file-carrying message. Cross-tenant by design."""
    ident = coerce(message_id)
    if ident is None:
        return None
    return db.scalar(select(M).where(M.id == ident, M.attachment != ""))


def attachment_for_download(
    db: Session, *, owner: User, attachment_id: uuid.UUID | str
) -> SupportAttachment | None:
    """One file from this client's chat, or ``None``."""
    ident = coerce(attachment_id)
    if ident is None:
        return None
    return db.scalar(
        select(A).where(A.id == ident, A.owner_id == owner.id, A.file != "")
    )


def staff_attachment_for_download(
    db: Session, *, attachment_id: uuid.UUID | str
) -> SupportAttachment | None:
    """Any client's file. Cross-tenant by design."""
    ident = coerce(attachment_id)
    if ident is None:
        return None
    return db.scalar(select(A).where(A.id == ident, A.file != ""))


def last_office_reply(db: Session, *, owner: User) -> SupportMessage | None:
    """The office's newest message in this client's chat, or ``None``."""
    return db.scalar(
        select(M)
        .where(
            M.owner_id == owner.id,
            # ``exclude(sender_id=owner)``: a reply whose staff account was
            # erased has no sender and still counts.
            (M.sender_id != owner.id) | M.sender_id.is_(None),
            M.deleted_at.is_(None),
        )
        .order_by(M.created_at.desc())
        .limit(1)
    )
