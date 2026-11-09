"""The office's replies, carried into the client's support bot.

An owner with a live support-bot chat gets every reply there as well as on
the site: its files first, then its words signed with the replier's name,
quoting the client's own Telegram message when the reply answers one.
Each Telegram message is recorded against the reply (``support_relays``,
bot "support"), so an edit rewrites the words and a delete takes them all
back. A guest who wrote from the bot gets the office's words the same way.

Without a live chat nothing is sent here; the main bot's «Javobni ko'rish»
(``announce_support``) is the client's notice then - and when the bot
turns out to be blocked, that notice is sent from here instead. A
temporary refusal (429, a timeout) is raised for the task to try again;
what already went is not sent twice.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import (
    BotBlocked,
    ChatUnreachable,
    TelegramError,
    TelegramTemporaryError,
)

from app.common.cache import cache
from app.common.hooks import on
from app.modules.accounts.models import User
from app.modules.notifications.bot import support_bot, support_bot_configured
from app.modules.notifications.constants import (
    ERROR_BLOCKED,
    ERROR_UNREACHABLE,
    SUPPORT_BOT_GUEST_SENT_KEY,
    SUPPORT_BOT_SEEN_TTL_SECONDS,
)
from app.modules.notifications.models import SupportBotChat
from app.modules.notifications.selectors import (
    support_bot_chat_for,
    support_bot_chat_for_guest,
)
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.support_desk import (
    message_files,
    send_attachment,
)
from app.modules.supportchat.constants import (
    RELAY_PART_FILE,
    RELAY_PART_TEXT,
    MessageKind,
    RelayBot,
    sticker_emoji,
)
from app.modules.supportchat.models import SupportGuestMessage, SupportMessage
from app.modules.supportchat.selectors import (
    bot_copies,
    staff_message_for_relay,
)
from app.modules.supportchat.services import (
    GUEST_ANSWERED,
    OFFICE_CHANGED,
    OFFICE_REPLIED,
    record_relay,
)

logger = logging.getLogger(__name__)

TEAM = "Yordam xizmati"


@on(OFFICE_REPLIED)
def queue_bot_reply(*, reply_id: Any, **_: Any) -> None:
    """Send from a worker; the hook fires after the reply committed."""
    if not support_bot_configured():
        return
    from app.modules.notifications.tasks import deliver_support_bot_reply_task

    try:
        deliver_support_bot_reply_task.delay(str(reply_id))
    except Exception:
        logger.warning("support bot reply not queued", exc_info=True)


@on(OFFICE_CHANGED)
def queue_bot_change(*, message_id: Any, **_: Any) -> None:
    if not support_bot_configured():
        return
    from app.modules.notifications.tasks import mirror_support_bot_change_task

    try:
        mirror_support_bot_change_task.delay(str(message_id))
    except Exception:
        logger.warning("support bot change not queued", exc_info=True)


@on(GUEST_ANSWERED)
def queue_bot_guest_answer(*, message_id: Any, **_: Any) -> None:
    if not support_bot_configured():
        return
    from app.modules.notifications.tasks import deliver_support_bot_guest_answer_task

    try:
        deliver_support_bot_guest_answer_task.delay(str(message_id))
    except Exception:
        logger.warning("support bot guest answer not queued", exc_info=True)


def signed(*, sender: User | None, body: str) -> str:
    """The reply's words under the replier's name, as HTML."""
    name = (sender.full_name or "").strip() if sender is not None else ""
    head = f"<b>{escaped(name)}</b> · {TEAM}" if name else f"<b>{TEAM}</b>"
    return f"{head}\n\n{escaped(body)}" if body else head


def reply_text(message: SupportMessage) -> str:
    """What the words part of a reply says now."""
    if message.kind == MessageKind.STICKER:
        body = sticker_emoji(message.sticker) or message.body
    else:
        body = message.body
    return signed(sender=message.sender, body=body)


def deliver_bot_reply(db: Session, *, reply_id: str, now: datetime) -> int:
    """Put one office reply in the owner's support bot. Returns how many
    Telegram messages went; 0 when there is no live chat, the reply is
    gone, or it went already (a task run twice sends nothing twice)."""
    message = staff_message_for_relay(db, message_id=reply_id)
    if (
        message is None
        or message.deleted_at is not None
        or message.sender_id == message.owner_id
        or not support_bot_configured()
    ):
        return 0
    row = support_bot_chat_for(db, owner=message.owner)
    if row is None:
        return 0
    already = [c for c in bot_copies(db, message=message) if c.chat_id == row.chat_id]
    if any(copy.part == RELAY_PART_TEXT for copy in already):
        return 0
    # A run that died after the files resumes with the words.
    files = (
        []
        if any(copy.part == RELAY_PART_FILE for copy in already)
        else message_files(db, message=message)
    )
    quoted = _quoted(db, message=message, row=row)
    sent = 0
    with support_bot() as client:
        for item, content in files:
            file_id = send_attachment(
                client=client, chat_id=row.chat_id, item=item, content=content
            )
            if file_id:
                record_relay(
                    db,
                    message=message,
                    chat_id=row.chat_id,
                    telegram_message_id=file_id,
                    bot=RelayBot.SUPPORT,
                    part=RELAY_PART_FILE,
                )
                sent += 1
        try:
            words = client.send_message(
                chat_id=row.chat_id, text=reply_text(message), reply_to=quoted
            )
        except TelegramTemporaryError:
            raise
        except TelegramError as exc:
            if _explain(db, row=row, exc=exc, now=now):
                _tell_elsewhere(db, message=message, now=now)
            return sent
    record_relay(
        db,
        message=message,
        chat_id=row.chat_id,
        telegram_message_id=words.message_id,
        bot=RelayBot.SUPPORT,
        part=RELAY_PART_TEXT,
    )
    logger.info(
        "support bot reply sent",
        extra={"message_id": str(message.id), "telegram_messages": sent + 1},
    )
    return sent + 1


def mirror_bot_change(db: Session, *, message_id: str) -> str:
    """An office message edited or taken back on the site, the same in the
    bot. Telegram lets a bot delete its own for 48 hours; after that the
    copy stays, and the site shows the truth."""
    message = staff_message_for_relay(db, message_id=message_id)
    if message is None or not support_bot_configured():
        return "gone"
    copies = bot_copies(db, message=message)
    if not copies:
        return "none"
    with support_bot() as client:
        if message.deleted_at is not None:
            for copy in copies:
                _quietly(
                    client.delete_message,
                    chat_id=copy.chat_id,
                    message_id=copy.telegram_message_id,
                )
            return "deleted"
        for copy in copies:
            if copy.part == RELAY_PART_TEXT:
                _quietly(
                    client.edit_message_text,
                    chat_id=copy.chat_id,
                    message_id=copy.telegram_message_id,
                    text=reply_text(message),
                )
    return "edited"


def deliver_bot_guest_answer(db: Session, *, message_id: str, now: datetime) -> bool:
    """The office's words to a guest who wrote from the bot."""
    try:
        message = db.get(SupportGuestMessage, uuid.UUID(message_id))
    except ValueError:
        return False
    if message is None or message.from_guest or not support_bot_configured():
        return False
    row = support_bot_chat_for_guest(db, guest_chat_id=message.chat_id)
    if row is None or not row.is_active or row.owner_id is not None:
        return False
    key = SUPPORT_BOT_GUEST_SENT_KEY.format(message_id=message.id)
    if not cache.add(key, 1, SUPPORT_BOT_SEEN_TTL_SECONDS):
        return False
    with support_bot() as client:
        try:
            client.send_message(
                chat_id=row.chat_id,
                text=signed(sender=message.sender, body=message.body),
            )
        except TelegramTemporaryError:
            # Not sent: the next try may send it.
            cache.delete(key)
            raise
        except TelegramError as exc:
            _explain(db, row=row, exc=exc, now=now)
            return False
    return True


def _quoted(db: Session, *, message: SupportMessage, row: SupportBotChat) -> int:
    """The Telegram message the reply answers, in this chat, or 0."""
    if message.reply_to_id is None:
        return 0
    target = db.get(SupportMessage, message.reply_to_id)
    if target is None:
        return 0
    for copy in bot_copies(db, message=target):
        if copy.chat_id == row.chat_id and copy.part != RELAY_PART_FILE:
            return copy.telegram_message_id
    return 0


def _tell_elsewhere(db: Session, *, message: SupportMessage, now: datetime) -> None:
    """The bot is gone: the main bot's «Javobni ko'rish», once per reply."""
    from app.modules.notifications.services.announce_support import (
        announce_support_reply,
    )

    announce_support_reply(
        db,
        owner=message.owner,
        subject=f"{message.conversation_id}:bot-gone:{message.id}",
        now=now,
    )


def _explain(
    db: Session, *, row: SupportBotChat, exc: TelegramError, now: datetime
) -> bool:
    """A chat that blocked the bot, or is gone, stops getting replies; the
    site still has them. Anything else is logged and left. True when the
    chat was switched off."""
    reason = (
        ERROR_BLOCKED
        if isinstance(exc, BotBlocked)
        else ERROR_UNREACHABLE
        if isinstance(exc, ChatUnreachable)
        else ""
    )
    logger.warning("support_bot_send_failed", extra={"reason": str(exc)})
    if not reason:
        return False
    row.is_active = False
    row.last_error = reason
    row.last_error_at = now
    db.commit()
    return True


def _quietly(call: Any, **fields: Any) -> None:
    try:
        call(**fields)
    except TelegramError as exc:
        logger.info("support_bot_change_skipped", extra={"reason": str(exc)})


__all__ = [
    "deliver_bot_guest_answer",
    "deliver_bot_reply",
    "mirror_bot_change",
    "queue_bot_change",
    "queue_bot_guest_answer",
    "queue_bot_reply",
    "reply_text",
    "signed",
]
