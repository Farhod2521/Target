"""Storing one message in a chat the caller already holds.

Both ways a message arrives - the client writing to their chat, and anyone
replying inside a chat by its id - end here, so the rate limit, the audit
pair and the phone message cannot drift between them.

Telling the other end is the notifications module's: the hooks below fire
once the write has committed.
"""

from datetime import UTC, datetime
from typing import Final

from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.common.hooks import fire
from app.common.throttle import hit
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.supportchat.constants import MESSAGE_BUCKET, MESSAGES_PER_MINUTE
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.exceptions import TooManyMessages
from app.modules.supportchat.models import SupportConversation, SupportMessage
from app.modules.supportchat.services._append import append_message
from app.modules.supportchat.services._journal import journal

# The client wrote: copy it to every member of Support in Telegram
# (Django's ``deliver_support_question_task``). Takes ``message_id``.
QUESTION_POSTED: Final = "supportchat.question_posted"
# The office replied: tell the client's phone, once per stretch of not
# reading (``deliver_support_reply_task``). Takes ``owner_id``, ``subject``.
REPLY_POSTED: Final = "supportchat.reply_posted"
# The office replied: mark the Telegram copies it answers
# (``mark_support_answered_task``). Takes ``reply_id``.
REPLY_ANSWERS_RELAYS: Final = "supportchat.reply_answers_relays"


def store_message(
    db: Session,
    *,
    conversation: SupportConversation,
    sender: User,
    draft: Draft,
    now: datetime,
) -> SupportMessage:
    """Append, journal, and tell the other end. Runs inside the caller's
    transaction, with ``conversation`` locked."""
    if not hit(
        bucket=MESSAGE_BUCKET,
        key=str(sender.id),
        limit=MESSAGES_PER_MINUTE,
        window_seconds=60,
    ):
        raise TooManyMessages
    read_before = conversation.client_read_at
    message = append_message(
        db, conversation=conversation, sender=sender, draft=draft, now=now
    )
    journal(
        db,
        conversation=conversation,
        actor=sender,
        action=ActionType.SUPPORT_REPLY,
        event=EventName.SUPPORT_MESSAGE_POSTED,
        payload={
            "message_id": str(message.id),
            "kind": str(message.kind),
            "body_chars": len(message.body),
            "files": len(draft.files) + (1 if draft.voice else 0),
            "sticker": message.sticker,
            "reply_to": str(message.reply_to_id or ""),
        },
        previous_state={},
        key=f"support-reply:{message.id}",
        now=now,
    )
    if sender.id != conversation.owner_id:
        _tell_client(db, conversation=conversation, read_before=read_before)
        on_commit(db, lambda: fire(REPLY_ANSWERS_RELAYS, reply_id=message.id))
    else:
        on_commit(db, lambda: fire(QUESTION_POSTED, message_id=message.id))
    return message


def _tell_client(
    db: Session, *, conversation: SupportConversation, read_before: datetime | None
) -> None:
    """One phone message per stretch of not reading: the subject carries the
    moment the client last looked."""
    marker = read_before.astimezone(UTC).isoformat() if read_before else "never"
    subject = f"{conversation.id}:{marker}"
    owner_id = conversation.owner_id
    on_commit(db, lambda: fire(REPLY_POSTED, owner_id=owner_id, subject=subject))
