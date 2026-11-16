"""What the owners' bot (@owners_tai_bot) does when somebody writes to it.

For an owner - an id in ``STAFF_BOT_ADMIN_IDS``, or staff with the Owner
role (or a superuser) whose office bot is linked to this Telegram: ``/admin`` (``/stat``) sends the
figures card, the same the 07:00 report sends; ``/start`` the card and a
word about asking; ``/yangi`` starts a new conversation; and anything typed
is a question for the office assistant, answered here. Anybody else gets
one sentence and their own Telegram id, so an owner who is not on the list
yet knows what to add.
"""

import logging
from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import BotClient, Command, TelegramError, TextMessage, read_update

from app.common.exceptions import DomainError
from app.modules.notifications.bot import owners_bot
from app.modules.notifications.constants import COMMAND_START, PRIVATE_CHAT
from app.modules.notifications.services.admin_stats import is_admin, send_stats
from app.modules.officeai.constants import TELEGRAM_THINKING
from app.modules.officeai.services.telegram import ask_from_telegram, forget_thread

logger = logging.getLogger(__name__)

HOW_TO_ASK = (
    "Savolingizni oddiy matn bilan yozing - ofis AI javob beradi. Masalan: "
    "«Bugun nechta odam ro'yxatdan o'tdi?»\n"
    "/admin - statistika kartasi, /yangi - yangi suhbat."
)
NEW_THREAD = "Yangi suhbat boshlandi. Savolingizni yozing."
NO_ASKER = "Ofis AI uchun saytda Owner rolidagi xodim yoki superuser topilmadi."


def handle_owners_update(db: Session, *, payload: dict[str, Any], now: datetime) -> str:
    """One delivery to the owners' bot, acted on. Returns a word for the log."""
    update = read_update(payload)
    if not isinstance(update, Command | TextMessage):
        return "ignored"
    if update.chat_type not in ("", PRIVATE_CHAT):
        return "ignored"
    with owners_bot() as client:
        if not is_admin(db, update.sender.id):
            _say(
                client=client,
                chat_id=update.chat_id,
                text=(
                    "Bu bot faqat egalar uchun.\n"
                    f"Sizning Telegram id: <code>{update.sender.id}</code>"
                ),
            )
            return "refused"
        if isinstance(update, TextMessage):
            return _ask(db, client=client, message=update, now=now)
        if update.name == "yangi":
            forget_thread(chat_id=update.chat_id)
            _say(client=client, chat_id=update.chat_id, text=NEW_THREAD)
            return "new"
        try:
            said = send_stats(db, client=client, chat_id=update.chat_id, now=now)
        except TelegramError as exc:
            logger.warning("owners_bot_stats_failed: %s", exc)
            return "failed"
        if update.name == COMMAND_START:
            _say(client=client, chat_id=update.chat_id, text=HOW_TO_ASK)
        return said


def _ask(db: Session, *, client: BotClient, message: TextMessage, now: datetime) -> str:
    """Write the question down, say it is being looked at, and leave the
    answer to a worker: it takes as long as the model takes."""
    from app.modules.officeai.tasks import answer_office_turn_in_telegram

    try:
        turn = ask_from_telegram(
            db,
            telegram_id=message.sender.id,
            chat_id=message.chat_id,
            question=message.text,
            now=now,
        )
    except DomainError as exc:
        _say(client=client, chat_id=message.chat_id, text=escape(str(exc)))
        return "refused"
    if turn is None:
        _say(client=client, chat_id=message.chat_id, text=NO_ASKER)
        return "no_asker"
    db.commit()
    try:
        notice = client.send_message(chat_id=message.chat_id, text=TELEGRAM_THINKING)
        notice_id = notice.message_id
    except TelegramError as exc:
        logger.info("owners_bot_notice_failed", extra={"reason": str(exc)})
        notice_id = 0
    answer_office_turn_in_telegram.delay(turn.turn_id, message.chat_id, notice_id)
    return "asked"


def _say(*, client: BotClient, chat_id: str, text: str) -> None:
    try:
        client.send_message(chat_id=chat_id, text=text)
    except TelegramError as exc:
        logger.info("owners_bot_say_failed", extra={"reason": str(exc)})


__all__ = ["handle_owners_update"]
