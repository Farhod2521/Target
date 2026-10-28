"""Finding one's own message to change it, under the rules both changes share.

Only the sender, only within the window, only while it stands. Looked up
by sender rather than by chat, so a message of somebody else's reads as
missing whoever asks.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.exceptions import NotAllowed
from app.modules.accounts.models import User
from app.modules.backoffice.services import may_answer_support
from app.modules.supportchat.exceptions import (
    EditWindowClosed,
    MessageGone,
    MessageNotYours,
)
from app.modules.supportchat.models import SupportMessage
from app.modules.supportchat.rules import may_change


def own_message(
    db: Session, *, message_id: uuid.UUID | str, sender: User, now: datetime
) -> SupportMessage:
    """The sender's message, locked, if it may still be changed."""
    try:
        ident = (
            message_id
            if isinstance(message_id, uuid.UUID)
            else uuid.UUID(str(message_id))
        )
    except ValueError:
        raise MessageNotYours from None
    message = db.scalar(
        select(SupportMessage)
        .where(SupportMessage.id == ident, SupportMessage.sender_id == sender.id)
        .with_for_update(of=SupportMessage)
    )
    if message is None:
        raise MessageNotYours
    if sender.id != message.owner_id and not may_answer_support(db, user=sender):
        raise NotAllowed("Bu suhbatga yoza olmaysiz.")
    if message.deleted_at is not None:
        raise MessageGone
    if not may_change(message=message, now=now):
        raise EditWindowClosed
    return message
