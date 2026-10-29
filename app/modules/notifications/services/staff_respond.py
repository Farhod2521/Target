"""What the staff bot does when somebody writes to it.

The office's bot; nothing a customer does reaches it. ``/start`` with a code
from the office links a member of staff, ``/stop`` unlinks them, a reply to
a client's copy goes back into that client's chat, and the two buttons
under a held second reply decide it. Anything else gets one sentence about
what the bot is for - there is no assistant here.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import (
    BotClient,
    ButtonPress,
    Command,
    TelegramError,
    TextMessage,
    read_update,
)

from app.modules.notifications.bot import staff_bot
from app.modules.notifications.constants import (
    COMMAND_START,
    COMMAND_STOP,
    PRIVATE_CHAT,
)
from app.modules.notifications.exceptions import StaffChatTaken, StaffLinkInvalid
from app.modules.notifications.models import StaffChat
from app.modules.notifications.selectors import staff_chat_by_id
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.link import link_staff_chat, stop_staff_chat
from app.modules.notifications.services.send import answer
from app.modules.notifications.services.support_confirm import (
    handle_support_press,
    is_support_press,
)
from app.modules.notifications.services.support_desk import answer_support_reply

logger = logging.getLogger(__name__)


def handle_staff_update(db: Session, *, payload: dict[str, Any], now: datetime) -> str:
    """One delivery to the staff bot, acted on. Returns a word for the log."""
    update = read_update(payload)
    if update is None:
        return "ignored"
    with staff_bot() as client:
        if isinstance(update, Command):
            return _command(db, client=client, command=update, now=now)
        chat = staff_chat_by_id(db, chat_id=update.chat_id)
        if isinstance(update, ButtonPress):
            return _press(db, client=client, chat=chat, press=update, now=now)
        if update.chat_type != PRIVATE_CHAT:
            return "ignored"
        if isinstance(update, TextMessage):
            replied = answer_support_reply(db, client=client, message=update, now=now)
            if replied:
                return replied
        _say(client=client, chat_id=update.chat_id, text=_help(chat))
        return "help"


def _command(db: Session, *, client: BotClient, command: Command, now: datetime) -> str:
    if command.name == COMMAND_STOP:
        stop_staff_chat(db, chat_id=command.chat_id)
        db.commit()
        _say(
            client=client,
            chat_id=command.chat_id,
            text="Uzildi. Qayta ulash uchun ofisdagi «Telegram» sahifasiga kiring.",
        )
        return "stopped"
    if command.name == COMMAND_START and command.argument:
        return _link(db, client=client, command=command, now=now)
    known = staff_chat_by_id(db, chat_id=command.chat_id)
    _say(client=client, chat_id=command.chat_id, text=_help(known))
    return "help"


def _link(db: Session, *, client: BotClient, command: Command, now: datetime) -> str:
    try:
        link_staff_chat(
            db,
            token=command.argument,
            chat_id=command.chat_id,
            username=command.sender.username,
            now=now,
        )
    except (StaffLinkInvalid, StaffChatTaken) as exc:
        db.rollback()
        _say(client=client, chat_id=command.chat_id, text=exc.message)
        return "refused"
    db.commit()
    _say(
        client=client,
        chat_id=command.chat_id,
        text=(
            "Ulandi. Ofisdagi rollaringiz bo'yicha xabarlar shu yerga keladi. "
            "To'xtatish uchun /stop."
        ),
    )
    return "linked"


def _press(
    db: Session,
    *,
    client: BotClient,
    chat: StaffChat | None,
    press: ButtonPress,
    now: datetime,
) -> str:
    if chat is None or press.sender.id != chat.chat_id:
        answer(
            client=client, query_id=press.query_id, text="Bu tugma sizga tegishli emas."
        )
        return "stranger"
    if is_support_press(press.data):
        return handle_support_press(db, client=client, chat=chat, press=press, now=now)
    answer(client=client, query_id=press.query_id, text="Tushunarsiz tugma.")
    return "unreadable"


def _help(chat: StaffChat | None) -> str:
    if chat is None or not chat.is_active:
        return (
            "Bu bot faqat xodimlar uchun. Ulash uchun ofisdagi «Telegram» "
            "sahifasidan havola oling."
        )
    return "Mijozga javob berish uchun uning xabariga «Reply» qiling. To'xtatish uchun /stop."


def _say(*, client: BotClient, chat_id: str, text: str) -> None:
    try:
        client.send_message(chat_id=chat_id, text=escaped(text))
    except TelegramError as exc:
        logger.info("staff_bot_say_failed", extra={"reason": str(exc)})


__all__ = ["handle_staff_update"]
