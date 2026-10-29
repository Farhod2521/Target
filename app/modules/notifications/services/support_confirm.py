"""A second reply to a client message somebody in Support already answered.

Held rather than sent. The bot says who answered and when, and offers two
buttons: send it after all, or drop it. A follow-up that was meant is one
press away; a reply typed into the wrong copy never reaches the client.
The held words wait in the cache under a short token the buttons carry -
until somebody presses "send" they are not a message.
"""

import logging
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import BotClient, Button, ButtonPress, TelegramError, TextMessage

from app.common.cache import cache
from app.common.dates import localtime
from app.common.exceptions import DomainError
from app.modules.backoffice.services import may_answer_support
from app.modules.notifications.constants import (
    SUPPORT_CONFIRM_KEY,
    SUPPORT_CONFIRM_TOKEN_BYTES,
    SUPPORT_CONFIRM_TTL_SECONDS,
)
from app.modules.notifications.keys import read_support_press, support_press_data
from app.modules.notifications.models import StaffChat
from app.modules.notifications.services.compose import escaped, support_confirm_message
from app.modules.notifications.services.send import answer, edit
from app.modules.supportchat.models import SupportMessage, SupportRelay
from app.modules.supportchat.selectors import staff_relay
from app.modules.supportchat.services import reply_from_telegram

logger = logging.getLogger(__name__)


def stamp(moment: datetime) -> str:
    """A moment as a member of staff reads it: day, month and time."""
    return localtime(moment).strftime("%d.%m %H:%M")


def signed(message: SupportMessage) -> str:
    """Who in the office wrote this, as the office knows them."""
    sender = message.sender
    if sender is None:
        return "Qo'llab-quvvatlash"
    return sender.full_name or sender.email


def hold_second_reply(
    *,
    client: BotClient,
    message: TextMessage,
    relay: SupportRelay,
    earlier: SupportMessage,
) -> None:
    """Keep the words and ask whether to send them anyway."""
    token = secrets.token_urlsafe(SUPPORT_CONFIRM_TOKEN_BYTES)
    cache.set(
        SUPPORT_CONFIRM_KEY.format(token=token),
        {"chat_id": message.chat_id, "relay_id": str(relay.id), "body": message.text},
        SUPPORT_CONFIRM_TTL_SECONDS,
    )
    text = support_confirm_message(name=signed(earlier), at=stamp(earlier.created_at))
    buttons = (
        Button(text="Ha, yuborish", data=support_press_data(send=True, token=token)),
        Button(text="Bekor qilish", data=support_press_data(send=False, token=token)),
    )
    try:
        client.send_message(
            chat_id=message.chat_id,
            text=text.text,
            buttons=buttons,
            reply_to=message.message_id,
        )
    except TelegramError as exc:
        logger.info("support_confirm_prompt_failed", extra={"reason": str(exc)})


def is_support_press(data: str) -> bool:
    return read_support_press(data) is not None


def handle_support_press(
    db: Session,
    *,
    client: BotClient,
    chat: StaffChat,
    press: ButtonPress,
    now: datetime,
) -> str:
    """ "Send it anyway" or "drop it", pressed under a held reply. The words
    leave the cache before anything is done with them, so a second press on
    the same button finds nothing and sends nothing."""
    parsed = read_support_press(press.data)
    if parsed is None:  # pragma: no cover - routed here only when it parses
        return "unreadable"
    send, token = parsed
    key = SUPPORT_CONFIRM_KEY.format(token=token)
    held: dict[str, Any] | None = cache.get(key)
    if held is None or held.get("chat_id") != chat.chat_id:
        _close(
            client=client,
            press=press,
            text="Bu so'rov eskirgan. Kerak bo'lsa, qayta reply qiling.",
        )
        return "support_expired"
    cache.delete(key)
    if not send:
        _close(client=client, press=press, text="Bekor qilindi. Javob yuborilmadi.")
        return "support_dropped"
    relay = staff_relay(db, pk=held["relay_id"])
    if relay is None or not may_answer_support(db, user=chat.owner):
        _close(client=client, press=press, text="Suhbat topilmadi.")
        return "support_missing"
    try:
        reply_from_telegram(
            db,
            conversation=relay.message.conversation,
            sender=chat.owner,
            body=str(held.get("body") or ""),
            now=now,
        )
    except DomainError as exc:
        _close(client=client, press=press, text=exc.message)
        return "support_refused"
    _close(client=client, press=press, text="Javob mijozga yuborildi.")
    return "support_replied"


def _close(*, client: BotClient, press: ButtonPress, text: str) -> None:
    """Replace the question and its buttons with what happened."""
    edit(
        client=client,
        chat_id=press.chat_id,
        message_id=press.message_id,
        text=escaped(text),
    )
    answer(client=client, query_id=press.query_id)


__all__ = [
    "handle_support_press",
    "hold_second_reply",
    "is_support_press",
    "signed",
    "stamp",
]
