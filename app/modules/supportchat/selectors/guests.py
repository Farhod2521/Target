"""Reading the sign-in page's chats: the guest's own, and the office's list."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.supportchat.constants import (
    CLIENT,
    GUEST_MESSAGES_SHOWN,
    OFFICE,
    WAITING,
    QueueState,
    Viewer,
)
from app.modules.supportchat.models import SupportGuestChat, SupportGuestMessage
from app.modules.supportchat.services.guests import token_hash

G = SupportGuestChat
# The office's list is short: guests are few, and a moved chat leaves it.
GUEST_QUEUE_SIZE = 100

# The guest spoke last, nobody settled it, and it is still a guest's.
GUEST_AWAITING_OFFICE = and_(
    G.claimed_at.is_(None),
    G.last_guest_at.is_not(None),
    or_(G.last_office_at.is_(None), G.last_office_at < G.last_guest_at),
    or_(G.settled_at.is_(None), G.settled_at < G.last_guest_at),
)


@dataclass(frozen=True, slots=True)
class GuestRow:
    chat: SupportGuestChat
    waiting: bool
    last: SupportGuestMessage | None


def guest_chat_by_token(db: Session, *, token: str) -> SupportGuestChat | None:
    if not token:
        return None
    return db.scalar(select(G).where(G.token_hash == token_hash(token)))


def guest_chat(db: Session, *, pk: uuid.UUID) -> SupportGuestChat | None:
    return db.get(G, pk)


def is_guest_waiting(*, chat: SupportGuestChat) -> bool:
    """:data:`GUEST_AWAITING_OFFICE` for one row already in hand."""
    guest = chat.last_guest_at
    if chat.claimed_at is not None or guest is None:
        return False
    office, settled = chat.last_office_at, chat.settled_at
    return (office is None or office < guest) and (settled is None or settled < guest)


def guest_messages(db: Session, *, chat: SupportGuestChat) -> list[SupportGuestMessage]:
    """The newest of the chat's messages, oldest first."""
    newest = list(
        db.scalars(
            select(SupportGuestMessage)
            .where(SupportGuestMessage.chat_id == chat.id)
            .order_by(
                SupportGuestMessage.created_at.desc(), SupportGuestMessage.id.desc()
            )
            .limit(GUEST_MESSAGES_SHOWN)
        )
    )
    return newest[::-1]


def guest_queue(db: Session, *, state: QueueState) -> list[GuestRow]:
    """Waiting ones oldest first, as the account queue; all of them newest first."""
    query = select(G).where(G.last_message_at.is_not(None))
    if state == WAITING:
        query = query.where(GUEST_AWAITING_OFFICE).order_by(G.last_guest_at)
    else:
        query = query.order_by(G.last_message_at.desc())
    chats = list(db.scalars(query.limit(GUEST_QUEUE_SIZE)))
    latest = _latest(db, [chat.id for chat in chats])
    return [
        GuestRow(
            chat=chat, waiting=is_guest_waiting(chat=chat), last=latest.get(chat.id)
        )
        for chat in chats
    ]


def guests_waiting_count(db: Session) -> int:
    return int(
        db.scalar(select(func.count()).select_from(G).where(GUEST_AWAITING_OFFICE)) or 0
    )


def _latest(
    db: Session, chat_ids: list[uuid.UUID]
) -> dict[uuid.UUID, SupportGuestMessage]:
    if not chat_ids:
        return {}
    M = SupportGuestMessage
    ranked = (
        select(
            M.id,
            func.row_number()
            .over(partition_by=M.chat_id, order_by=(M.created_at.desc(), M.id.desc()))
            .label("rank"),
        )
        .where(M.chat_id.in_(chat_ids))
        .subquery()
    )
    rows = db.scalars(
        select(M).join(ranked, ranked.c.id == M.id).where(ranked.c.rank == 1)
    )
    return {row.chat_id: row for row in rows}


def guest_message_view(
    message: SupportGuestMessage, *, chat: SupportGuestChat, viewer: Viewer
) -> dict[str, Any]:
    """One message as the guest or the office reads it."""
    side = CLIENT if message.from_guest else OFFICE
    own = side == viewer
    if viewer == CLIENT:
        who = "Siz" if own else "Qo'llab-quvvatlash"
    elif message.from_guest:
        who = chat.name
    else:
        sender = message.sender
        who = (sender.full_name or sender.email) if sender else "Qo'llab-quvvatlash"
    seen = chat.office_read_at if side == CLIENT else chat.guest_read_at
    return {
        "id": str(message.id),
        "side": side,
        "own": own,
        "who": who,
        "body": message.body,
        "created_at": message.created_at,
        "at": int(message.created_at.timestamp() * 1000),
        "read": own and seen is not None and seen >= message.created_at,
    }
