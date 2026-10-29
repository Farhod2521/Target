"""The office's side of the support chat, in the staff bot.

Every message a client writes to Support is copied to each member of
Support who has linked the staff bot - never the customer bot, which the
business owner also uses for their own advertising. A reply to that copy -
Telegram's own "Reply" - comes back into the client's chat, signed by
whoever wrote it, through the service the office console uses.

Once anybody answers, every copy is marked answered (``support_answered``),
and a reply to an answered copy is held and asked about rather than sent
(``support_confirm``): two people answering one question is the mistake the
mark exists for.

The client's files go up first - pictures as photos, anything else as a
document - and the copy quotes the first. Only text comes back; the console
takes files.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import (
    DOCUMENT_MAX_BYTES,
    PHOTO_MAX_BYTES,
    BotClient,
    SentMessage,
    TelegramError,
    TextMessage,
)

from app.common import storage
from app.common.exceptions import DomainError
from app.common.hooks import on
from app.common.routes import reverse
from app.modules.backoffice.services import may_answer_support
from app.modules.notifications.bot import staff_bot, staff_bot_configured
from app.modules.notifications.models import StaffChat
from app.modules.notifications.selectors import staff_chat_by_id, staff_chats_where
from app.modules.notifications.services.compose import (
    Message,
    escaped,
    support_question_message,
)
from app.modules.notifications.services.support_confirm import hold_second_reply
from app.modules.supportchat.constants import MessageKind
from app.modules.supportchat.models import SupportAttachment, SupportMessage
from app.modules.supportchat.preview import preview_text
from app.modules.supportchat.selectors import (
    office_answer_after,
    relay_for,
    relayed_chat_ids,
    staff_message_for_relay,
)
from app.modules.supportchat.services import (
    QUESTION_POSTED,
    record_relay,
    reply_from_telegram,
)

logger = logging.getLogger(__name__)

# Telegram draws these as a photo. A GIF would lose its motion there, so it
# goes as a document like everything else.
PHOTO_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})


@dataclass(frozen=True, slots=True)
class RelayedFile:
    """One file of a client's message, as the copy carries it."""

    stored: str
    name: str
    kind: str
    size: int


@on(QUESTION_POSTED)
def queue_support_question(*, message_id: Any, **_: Any) -> None:
    """Copy the message to the office from a worker; the hook fires after
    the chat's commit, so a rolled-back message is never announced."""
    from app.modules.notifications.tasks import deliver_support_question_task

    try:
        deliver_support_question_task.delay(str(message_id))
    except Exception:
        logger.warning("support question not queued", exc_info=True)


def question_for(db: Session, *, message: SupportMessage) -> Message:
    """The office's copy of one client message. Built again, unchanged,
    when the copy is marked answered."""
    owner = message.owner
    rows = _attachments(db, message)
    names = [item.name for item in _files_of(message, rows)]
    voice = message.kind == MessageKind.VOICE
    return support_question_message(
        client=f"{owner.full_name or owner.email} · {owner.email}",
        # A sticker's emoji and a voice's length stand where words would.
        body=message.body
        or (preview_text(message, rows) if not names or voice else ""),
        file_name="" if voice else ", ".join(names),
        office_path=reverse("backoffice:support_thread", [message.conversation_id]),
    )


def forward_support_question(db: Session, *, message_id: str, now: datetime) -> int:
    """Send the copy to every member of Support with the staff bot linked.

    Returns how many went out. Each is recorded against its Telegram id -
    how a reply finds its way back, and which chats already hold a copy, so
    a redelivered task sends nothing twice.
    """
    message = staff_message_for_relay(db, message_id=message_id)
    if message is None or not staff_bot_configured():
        return 0
    already = relayed_chat_ids(db, message=message)
    chats = [chat for chat in office_chats(db) if chat.chat_id not in already]
    if not chats:
        return 0
    files = [
        (item, content)
        for item in _files_of(message, _attachments(db, message))
        if (content := attachment_bytes(item=item)) is not None
    ]
    text = question_for(db, message=message).text
    copies = 0
    with staff_bot() as client:
        for chat in chats:
            ids = [
                send_attachment(
                    client=client, chat_id=chat.chat_id, item=item, content=content
                )
                for item, content in files
            ]
            quoted = next((sent for sent in ids if sent), 0)
            sent = _send(
                client=client, chat_id=chat.chat_id, text=text, reply_to=quoted
            )
            if sent:
                record_relay(
                    db, message=message, chat_id=chat.chat_id, telegram_message_id=sent
                )
                copies += 1
    logger.info(
        "support question relayed",
        extra={"message_id": str(message.id), "copies": copies},
    )
    return copies


def _attachments(db: Session, message: SupportMessage) -> list[SupportAttachment]:
    return list(
        db.scalars(
            select(SupportAttachment)
            .where(SupportAttachment.message_id == message.id)
            .order_by(SupportAttachment.position)
        )
    )


def _files_of(
    message: SupportMessage, attachments: list[SupportAttachment]
) -> list[RelayedFile]:
    """Every file the message carries: its rows, or its own from before."""
    rows = [
        RelayedFile(
            stored=row.file, name=row.original_name, kind=row.kind, size=row.size_bytes
        )
        for row in attachments
    ]
    if message.attachment:
        rows.append(
            RelayedFile(
                stored=message.attachment,
                name=message.original_name,
                kind=message.kind,
                size=message.size_bytes,
            )
        )
    return rows


def attachment_bytes(*, item: RelayedFile) -> bytes | None:
    """One file, read once for every copy. ``None`` when Telegram would
    refuse it for size or it has gone from the disk - the copy names it,
    and the console has it."""
    if item.size > DOCUMENT_MAX_BYTES:
        return None
    try:
        return storage.media_path(item.stored).read_bytes()
    except (OSError, ValueError):
        logger.warning("support attachment unreadable", extra={"name": item.name})
        return None


def send_attachment(
    *, client: BotClient, chat_id: str, item: RelayedFile, content: bytes
) -> int:
    """Put one of the client's files in one member's chat. Its Telegram id
    for the copy to quote, or ``0`` - the copy still goes, naming the file."""
    name = item.name or PurePosixPath(item.stored or "fayl").name
    as_photo = (
        item.kind == MessageKind.IMAGE
        and len(content) <= PHOTO_MAX_BYTES
        and PurePosixPath(name).suffix.lower() in PHOTO_SUFFIXES
    )
    if as_photo:
        # A photo Telegram will not draw - too long a screenshot - is still
        # a file it will carry.
        sent = _upload(client.send_photo, chat_id=chat_id, name=name, content=content)
        if sent:
            return sent
    return _upload(client.send_document, chat_id=chat_id, name=name, content=content)


def _upload(
    send: Callable[..., SentMessage], *, chat_id: str, name: str, content: bytes
) -> int:
    try:
        return send(chat_id=chat_id, filename=name, content=content).message_id
    except TelegramError as exc:
        logger.info("support_attachment_not_sent", extra={"reason": str(exc)})
        return 0


def answer_support_reply(
    db: Session, *, client: BotClient, message: TextMessage, now: datetime
) -> str:
    """A reply to one of those copies, stored in the client's chat.

    Empty when this is not such a reply - it quotes something else, or the
    writer does not answer Support - so the caller carries on. A reply to a
    copy somebody already answered is held and asked about instead.
    """
    if not message.reply_to_message_id:
        return ""
    chat = staff_chat_by_id(db, chat_id=message.chat_id)
    if chat is None or not may_answer_support(db, user=chat.owner):
        return ""
    relay = relay_for(
        db, chat_id=message.chat_id, telegram_message_id=message.reply_to_message_id
    )
    if relay is None:
        return ""
    earlier = office_answer_after(db, message=relay.message)
    if earlier is not None:
        hold_second_reply(client=client, message=message, relay=relay, earlier=earlier)
        return "support_held"
    try:
        reply_from_telegram(
            db,
            conversation=relay.message.conversation,
            sender=chat.owner,
            body=message.text,
            now=now,
        )
    except DomainError as exc:
        say(
            client=client,
            chat_id=message.chat_id,
            text=exc.message,
            reply_to=message.message_id,
        )
        return "support_refused"
    say(
        client=client,
        chat_id=message.chat_id,
        text="Javob mijozga yuborildi.",
        reply_to=message.message_id,
    )
    return "support_replied"


def office_chats(db: Session) -> list[StaffChat]:
    """Live staff-bot links whose owner answers Support."""
    return staff_chats_where(db, allowed=lambda user: may_answer_support(db, user=user))


def _send(*, client: BotClient, chat_id: str, text: str, reply_to: int) -> int:
    try:
        return client.send_message(
            chat_id=chat_id, text=text, reply_to=reply_to
        ).message_id
    except TelegramError as exc:
        logger.warning("support_copy_not_sent", extra={"reason": str(exc)})
        return 0


def say(*, client: BotClient, chat_id: str, text: str, reply_to: int = 0) -> None:
    """A short line to a member of staff; lost if Telegram refuses it."""
    try:
        client.send_message(chat_id=chat_id, text=escaped(text), reply_to=reply_to)
    except TelegramError as exc:
        logger.info("support_desk_say_failed", extra={"reason": str(exc)})


__all__ = [
    "RelayedFile",
    "answer_support_reply",
    "attachment_bytes",
    "forward_support_question",
    "office_chats",
    "question_for",
    "queue_support_question",
    "say",
    "send_attachment",
]
