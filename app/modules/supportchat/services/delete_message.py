"""The sender taking back their own message."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common import storage
from app.common.db import on_commit
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.supportchat.models import SupportAttachment, SupportMessage
from app.modules.supportchat.services._journal import journal
from app.modules.supportchat.services._own import own_message
from app.modules.supportchat.services._tx import atomic


def delete_message(
    db: Session, *, message_id: uuid.UUID | str, sender: User, now: datetime
) -> SupportMessage:
    """Take back a message sent within the last day.

    The row stays, so the chat reads "o'chirildi" where it stood and an
    answer quoting it still has something to point at; what it said and
    carried goes - the words onto the audit row, the files off the disk
    once the change has committed.
    """

    def run() -> SupportMessage:
        message = own_message(db, message_id=message_id, sender=sender, now=now)
        attachments = list(
            db.scalars(
                select(SupportAttachment)
                .where(SupportAttachment.message_id == message.id)
                .order_by(SupportAttachment.position)
            )
        )
        files = [row.file for row in attachments if row.file]
        if message.attachment:
            files.append(message.attachment)
        previous = {
            "body": message.body,
            "sticker": message.sticker,
            "files": [row.original_name for row in attachments]
            + ([message.original_name] if message.attachment else []),
        }
        db.execute(
            delete(SupportAttachment).where(SupportAttachment.message_id == message.id)
        )
        message.body = ""
        message.sticker = ""
        message.attachment = ""
        message.original_name = ""
        message.size_bytes = 0
        message.deleted_at = now
        db.flush()
        journal(
            db,
            conversation=message.conversation,
            actor=sender,
            action=ActionType.SUPPORT_DELETE,
            event=EventName.SUPPORT_MESSAGE_DELETED,
            payload={"message_id": str(message.id)},
            previous_state=previous,
            key=f"support-delete:{message.id}",
            now=now,
        )
        on_commit(db, lambda: _remove(files))
        return message

    return atomic(db, run)


def _remove(files: list[str]) -> None:
    """The bytes, after the rows are gone. A file already missing is fine."""
    for name in files:
        storage.delete(name)
