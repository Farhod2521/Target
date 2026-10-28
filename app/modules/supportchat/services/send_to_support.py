"""The client writing to the office - into their one chat, started by the
first message they ever send."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.models import SupportConversation, SupportMessage
from app.modules.supportchat.services._journal import journal
from app.modules.supportchat.services._once import once
from app.modules.supportchat.services._store import store_message
from app.modules.supportchat.services._tx import atomic


def send_to_support(
    db: Session,
    *,
    owner: User,
    draft: Draft,
    now: datetime,
    send_key: str = "",
) -> SupportMessage:
    """Store one message from this client, once per ``send_key``. The chat
    and the message commit together or not at all: a refused first message
    leaves no empty chat in the office's list."""

    def run() -> SupportMessage:
        conversation = chat_of_client(db, owner=owner, now=now)
        return store_message(
            db, conversation=conversation, sender=owner, draft=draft, now=now
        )

    with once(sender=owner, key=send_key):
        return atomic(db, run)


def chat_of_client(
    db: Session, *, owner: User, now: datetime, opened_by: User | None = None
) -> SupportConversation:
    """This client's chat, locked - written now if this is the first word.

    ``opened_by`` is who wrote that word: the client, or a member of the
    office writing first. Two first messages racing meet the
    one-chat-per-client constraint, and the loser reads the winner's row.
    """
    created = False
    if (
        db.scalar(
            select(SupportConversation.id).where(
                SupportConversation.owner_id == owner.id
            )
        )
        is None
    ):
        try:
            with db.begin_nested():
                db.add(SupportConversation(owner_id=owner.id))
            created = True
        except IntegrityError:
            created = False
    locked = db.scalar(
        select(SupportConversation)
        .where(SupportConversation.owner_id == owner.id)
        .with_for_update(of=SupportConversation)
        .execution_options(populate_existing=True)
    )
    if locked is None:  # pragma: no cover - the row was written just above
        raise LookupError("support conversation vanished")
    if created:
        journal(
            db,
            conversation=locked,
            actor=opened_by or owner,
            action=ActionType.SUPPORT_OPEN,
            event=EventName.SUPPORT_CONVERSATION_OPENED,
            payload={},
            previous_state={},
            key=f"support-open:{locked.id}",
            now=now,
        )
    return locked
