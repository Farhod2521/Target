"""The one way a message row comes to exist.

Every message is stored through here, so the content rules, the file
handling and the chat's bookkeeping cannot drift between the client's
first message and every reply after it. Permission and audit stay with the
callers.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.supportchat.constants import MAX_BODY_CHARS, STICKER_CODES, MessageKind
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.exceptions import (
    EmptyMessage,
    MessageTooLong,
    MixedMessage,
    ReplyTargetMissing,
    UnknownSticker,
)
from app.modules.supportchat.models import SupportConversation, SupportMessage
from app.modules.supportchat.services._files import (
    Checked,
    checked_files,
    checked_voice,
    store_files,
)

logger = logging.getLogger(__name__)


def append_message(
    db: Session,
    *,
    conversation: SupportConversation,
    sender: User,
    draft: Draft,
    now: datetime,
) -> SupportMessage:
    """Validate, store and file one message. The row, not the journal.

    ``conversation`` is the locked row the caller is already holding: the
    moments are updated beside the insert, in the same transaction.
    """
    text = (draft.body or "").strip()
    files = _checked(draft=draft, text=text)
    reply_to = _reply_target(db, conversation=conversation, raw=draft.reply_to)
    message = SupportMessage(
        id=uuid.uuid4(),
        owner_id=conversation.owner_id,
        conversation_id=conversation.id,
        sender_id=sender.id,
        body=text,
        sticker=draft.sticker,
        reply_to_id=reply_to.id if reply_to is not None else None,
        kind=_kind(draft=draft, files=files),
        # What the lists show without reading the files: the first name,
        # and how much the send weighed.
        original_name=files[0].name if files else "",
        size_bytes=sum(item.size for item in files),
    )
    db.add(message)
    db.flush()
    store_files(db, message=message, files=files, now=now)
    _touch(conversation=conversation, sender=sender, now=now)
    db.flush()

    logger.info(
        "support message stored",
        extra={
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
            "kind": str(message.kind),
            "files": len(files),
        },
    )
    return message


def _checked(*, draft: Draft, text: str) -> list[Checked]:
    """What may go, or the reason nothing does. Nothing is written yet."""
    if len(text) > MAX_BODY_CHARS:
        raise MessageTooLong(MAX_BODY_CHARS)
    if draft.sticker:
        if text or draft.files or draft.voice:
            raise MixedMessage
        if draft.sticker not in STICKER_CODES:
            raise UnknownSticker
        return []
    if draft.voice is not None:
        if text or draft.files:
            raise MixedMessage
        return [checked_voice(voice=draft.voice)]
    files = checked_files(files=draft.files)
    if not files and not text:
        raise EmptyMessage
    return files


def _kind(*, draft: Draft, files: list[Checked]) -> MessageKind:
    if draft.sticker:
        return MessageKind.STICKER
    return files[0].kind if files else MessageKind.TEXT


def _reply_target(
    db: Session, *, conversation: SupportConversation, raw: str
) -> SupportMessage | None:
    """The answered message, from this chat and still standing, or nothing
    asked for. An id that names anything else is refused, not dropped."""
    if not raw:
        return None
    try:
        ident = uuid.UUID(str(raw))
    except ValueError:
        raise ReplyTargetMissing from None
    target = db.scalar(
        select(SupportMessage).where(
            SupportMessage.id == ident,
            SupportMessage.conversation_id == conversation.id,
            SupportMessage.deleted_at.is_(None),
        )
    )
    if target is None:
        raise ReplyTargetMissing
    return target


def _touch(*, conversation: SupportConversation, sender: User, now: datetime) -> None:
    """The moments the lists read."""
    conversation.last_message_at = now
    if sender.id == conversation.owner_id:
        conversation.last_client_at = now
        # The client has seen everything up to what they just wrote.
        conversation.client_read_at = now
    else:
        conversation.last_office_at = now
        # So has the office, writing into it.
        conversation.office_read_at = now
