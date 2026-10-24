import logging
from datetime import datetime

from sqlalchemy.orm import Session
from telegramkit import (
    BotBlocked,
    BotClient,
    Button,
    ChatUnreachable,
    TelegramAPIError,
    TelegramError,
    TelegramRateLimited,
)

from app.modules.notifications.constants import ERROR_BLOCKED, ERROR_UNREACHABLE
from app.modules.notifications.models import TelegramChat

logger = logging.getLogger(__name__)


def send_to(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    text: str,
    buttons: tuple[Button, ...] = (),
    now: datetime,
    reply_to: int = 0,
) -> int:
    """Send and return the message id; 0 when Telegram refused, explained."""
    try:
        sent = client.send_message(
            chat_id=chat.chat_id, text=text, buttons=buttons, reply_to=reply_to
        )
    except TelegramError as exc:
        _explain(db, chat=chat, exc=exc, now=now)
        return 0
    return sent.message_id


def edit(
    *,
    client: BotClient,
    chat_id: str,
    message_id: int,
    text: str,
    buttons: tuple[Button, ...] = (),
) -> None:
    try:
        client.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, buttons=buttons
        )
    except TelegramError as exc:
        logger.info("telegram_edit_skipped", extra={"reason": str(exc)})


def edit_buttons(
    *,
    client: BotClient,
    chat_id: str,
    message_id: int,
    buttons: tuple[Button, ...] = (),
) -> None:
    try:
        client.edit_message_buttons(
            chat_id=chat_id, message_id=message_id, buttons=buttons
        )
    except TelegramError as exc:
        logger.info("telegram_buttons_skipped", extra={"reason": str(exc)})


def answer(
    *, client: BotClient, query_id: str, text: str = "", alert: bool = False
) -> None:
    try:
        client.answer_callback_query(query_id=query_id, text=text, alert=alert)
    except TelegramError as exc:
        logger.info("telegram_answer_failed", extra={"reason": str(exc)})


def _explain(
    db: Session, *, chat: TelegramChat, exc: TelegramError, now: datetime
) -> None:
    from app.modules.notifications.services.link import deactivate

    if isinstance(exc, BotBlocked):
        deactivate(db, chat=chat, reason=ERROR_BLOCKED, now=now)
        return
    if isinstance(exc, ChatUnreachable):
        deactivate(db, chat=chat, reason=ERROR_UNREACHABLE, now=now)
        return
    if isinstance(exc, TelegramRateLimited):
        logger.warning(
            "telegram_rate_limited",
            extra={"retry_after": exc.retry_after, "chat": chat.chat_id},
        )
        return
    logger.warning(
        "telegram_send_failed",
        extra={
            "reason": str(exc),
            "chat": chat.chat_id,
            "answered": isinstance(exc, TelegramAPIError),
        },
    )


__all__ = ["answer", "edit", "edit_buttons", "send_to"]
