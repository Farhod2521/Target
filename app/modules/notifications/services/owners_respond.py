"""What the owners' bot (@owners_tai_bot) does when somebody writes to it.

``/start``, ``/admin``, ``/stat`` - and anything else - from an id in
``STAFF_BOT_ADMIN_IDS`` gets the figures card at once, the same card the
07:00 report sends. Anybody else gets one sentence and their own Telegram
id, so an owner who is not on the list yet knows what to add.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import BotClient, Command, TelegramError, TextMessage, read_update

from app.modules.notifications.bot import owners_bot
from app.modules.notifications.constants import PRIVATE_CHAT
from app.modules.notifications.services.admin_stats import is_admin, send_stats

logger = logging.getLogger(__name__)


def handle_owners_update(db: Session, *, payload: dict[str, Any], now: datetime) -> str:
    """One delivery to the owners' bot, acted on. Returns a word for the log."""
    update = read_update(payload)
    if not isinstance(update, Command | TextMessage):
        return "ignored"
    if update.chat_type not in ("", PRIVATE_CHAT):
        return "ignored"
    with owners_bot() as client:
        if not is_admin(update.sender.id):
            _say(
                client=client,
                chat_id=update.chat_id,
                text=(
                    "Bu bot faqat egalar uchun.\n"
                    f"Sizning Telegram id: <code>{update.sender.id}</code>"
                ),
            )
            return "refused"
        try:
            return send_stats(db, client=client, chat_id=update.chat_id, now=now)
        except TelegramError as exc:
            logger.warning("owners_bot_stats_failed: %s", exc)
            return "failed"


def _say(*, client: BotClient, chat_id: str, text: str) -> None:
    try:
        client.send_message(chat_id=chat_id, text=text)
    except TelegramError as exc:
        logger.info("owners_bot_say_failed", extra={"reason": str(exc)})


__all__ = ["handle_owners_update"]
