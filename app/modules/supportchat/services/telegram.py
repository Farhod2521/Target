"""Messages that arrive from Telegram, and the office's copies of them."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.modules.accounts.models import User
from app.modules.supportchat.constants import RelayBot
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.live import broadcast_message
from app.modules.supportchat.models import (
    SupportConversation,
    SupportMessage,
    SupportRelay,
)
from app.modules.supportchat.services.post_message import post_message
from app.modules.supportchat.services.send_to_support import send_to_support


def reply_from_telegram(
    db: Session,
    *,
    conversation: SupportConversation,
    sender: User,
    body: str,
    now: datetime,
) -> SupportMessage:
    """A member of Support answering a client from Telegram: stored through
    the console's own service, then put on the client's screen."""
    message = post_message(
        db, conversation=conversation, sender=sender, draft=Draft(body=body), now=now
    )
    broadcast_message(message=message)
    return message


def write_from_telegram(
    db: Session, *, owner: User, body: str, now: datetime
) -> SupportMessage:
    """A client writing to Support from the customer bot, through the
    cabinet's own service, then put on the office's screens."""
    message = send_to_support(db, owner=owner, draft=Draft(body=body), now=now)
    broadcast_message(message=message)
    return message


def record_relay(
    db: Session, *, message: SupportMessage, chat_id: str, telegram_message_id: int
) -> SupportRelay:
    """Tie one Telegram copy to the client message it carries. Bookkeeping,
    no journal; idempotent on the Telegram pair."""

    def found() -> SupportRelay | None:
        return db.scalar(
            select(SupportRelay).where(
                SupportRelay.bot == RelayBot.STAFF,
                SupportRelay.chat_id == chat_id,
                SupportRelay.telegram_message_id == telegram_message_id,
            )
        )

    relay = found()
    if relay is None:
        try:
            with db.begin_nested():
                relay = SupportRelay(
                    owner_id=message.owner_id,
                    message_id=message.id,
                    bot=RelayBot.STAFF,
                    chat_id=chat_id,
                    telegram_message_id=telegram_message_id,
                )
                db.add(relay)
        except IntegrityError:
            relay = found()
    db.commit()
    if relay is None:  # pragma: no cover - lost a race to a row now gone
        raise LookupError("support relay vanished")
    return relay


def mark_relays_answered(
    db: Session, *, relays: list[SupportRelay], reply: SupportMessage
) -> list[SupportRelay]:
    """Stamp each copy with the reply that answered it. Returns the copies
    this call stamped - one another worker got to first is left out."""
    marked: list[SupportRelay] = []
    for relay in relays:
        updated = db.execute(
            update(SupportRelay)
            .where(SupportRelay.id == relay.id, SupportRelay.answered_at.is_(None))
            .values(
                answered_at=reply.created_at,
                answered_by_id=reply.sender_id,
                updated_at=SupportRelay.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        if updated.rowcount:
            set_committed_value(relay, "answered_at", reply.created_at)
            set_committed_value(relay, "answered_by_id", reply.sender_id)
            marked.append(relay)
    db.commit()
    return marked
