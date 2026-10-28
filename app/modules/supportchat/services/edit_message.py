"""The sender changing the words of their own message."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.supportchat.constants import MAX_BODY_CHARS, MessageKind
from app.modules.supportchat.exceptions import (
    EmptyMessage,
    MessageTooLong,
    NothingToEdit,
)
from app.modules.supportchat.models import SupportMessage
from app.modules.supportchat.services._journal import journal
from app.modules.supportchat.services._own import own_message
from app.modules.supportchat.services._tx import atomic


def edit_message(
    db: Session,
    *,
    message_id: uuid.UUID | str,
    sender: User,
    body: str,
    now: datetime,
) -> SupportMessage:
    """New words on a message sent within the last day.

    The files stay as they were: a message that carries files may lose its
    words, one that is words alone may not. A sticker and a voice have no
    words to change. The words before are kept on the audit row.
    """

    def run() -> SupportMessage:
        message = own_message(db, message_id=message_id, sender=sender, now=now)
        if message.kind in (MessageKind.STICKER, MessageKind.VOICE):
            raise NothingToEdit
        text = (body or "").strip()
        if len(text) > MAX_BODY_CHARS:
            raise MessageTooLong(MAX_BODY_CHARS)
        if not text and not (message.size_bytes or message.attachment):
            raise EmptyMessage
        if text == message.body:
            return message
        before = message.body
        message.body = text
        message.edited_at = now
        db.flush()
        journal(
            db,
            conversation=message.conversation,
            actor=sender,
            action=ActionType.SUPPORT_EDIT,
            event=EventName.SUPPORT_MESSAGE_EDITED,
            payload={"message_id": str(message.id), "body_chars": len(text)},
            previous_state={"body": before},
            # A message may be edited twice: the key is fresh each time.
            key=f"support-edit:{uuid.uuid4().hex}",
            now=now,
        )
        return message

    return atomic(db, run)
