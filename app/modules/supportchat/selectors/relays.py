"""Reading a client message on its way to Telegram, and back.

Both directions are the office's. Cross-tenant by design, like the staff
half of ``conversations`` - callers prove the role before calling.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modules.supportchat.constants import RelayBot
from app.modules.supportchat.models import SupportMessage, SupportRelay
from app.modules.supportchat.selectors.conversations import coerce

M = SupportMessage
R = SupportRelay


def staff_message_for_relay(
    db: Session, *, message_id: uuid.UUID | str
) -> SupportMessage | None:
    """Any client's message with its sender, for the copy the office gets."""
    ident = coerce(message_id)
    if ident is None:
        return None
    return db.scalar(
        select(M)
        .options(
            selectinload(M.owner), selectinload(M.sender), selectinload(M.conversation)
        )
        .where(M.id == ident)
    )


def relay_for(
    db: Session, *, chat_id: str, telegram_message_id: int
) -> SupportRelay | None:
    """The copy a Telegram message is, or ``None`` when it is not one."""
    return db.scalar(
        select(R).where(
            R.bot == RelayBot.STAFF,
            R.chat_id == chat_id,
            R.telegram_message_id == telegram_message_id,
        )
    )


def staff_relay(db: Session, *, pk: uuid.UUID | str) -> SupportRelay | None:
    """One copy by its id, for a confirmation pressed later."""
    ident = coerce(pk)
    if ident is None:
        return None
    return db.scalar(select(R).where(R.id == ident, R.bot == RelayBot.STAFF))


def office_answer_after(
    db: Session, *, message: SupportMessage
) -> SupportMessage | None:
    """The office's first reply after this client message, or ``None``."""
    return db.scalar(
        select(M)
        .where(
            M.owner_id == message.owner_id,
            M.conversation_id == message.conversation_id,
            M.created_at >= message.created_at,
            (M.sender_id != message.owner_id) | M.sender_id.is_(None),
        )
        .order_by(M.created_at)
        .limit(1)
    )


def unanswered_relays(db: Session, *, reply: SupportMessage) -> list[SupportRelay]:
    """The copies of every client message this reply answers: in its chat,
    written no later than it, and not yet marked."""
    return list(
        db.scalars(
            select(R)
            .join(M, M.id == R.message_id)
            .where(
                R.owner_id == reply.owner_id,
                M.conversation_id == reply.conversation_id,
                M.created_at <= reply.created_at,
                R.answered_at.is_(None),
                R.bot == RelayBot.STAFF,
            )
        )
    )


def relayed_chat_ids(db: Session, *, message: SupportMessage) -> set[str]:
    """The Telegram chats this message already reached."""
    return set(
        db.scalars(
            select(R.chat_id).where(
                R.owner_id == message.owner_id,
                R.message_id == message.id,
                R.bot == RelayBot.STAFF,
            )
        )
    )
