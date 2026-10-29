"""What the customer bot does when somebody writes to it.

``/start`` with a code links an account, ``/stop`` unlinks it, ``/yordam``
makes the next typed words a message to Support. A stranger and an unlinked
chat get the one sentence about connecting.

Not here yet, from Django: the assistant answering typed questions, the
buttons under notices (suggestions, pauses, survey, daily report), the
``/hisobot`` and ``/bugun`` reports, and the new-password link for
``/start parol``. Until they are, those get the bot's help sentence, a
press is answered "not available", and ``parol`` points at Support.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import (
    BotClient,
    ButtonPress,
    Command,
    OtherMessage,
    TelegramError,
    TextMessage,
    read_update,
)

from app.common.cache import cache
from app.common.exceptions import DomainError
from app.common.i18n import DEFAULT, override
from app.modules.notifications.bot import bot
from app.modules.notifications.constants import (
    COMMAND_HELP,
    COMMAND_START,
    COMMAND_STOP,
    PRIVATE_CHAT,
    RESET_PAYLOAD,
    SUPPORT_WAIT_KEY,
    SUPPORT_WAIT_TTL_SECONDS,
)
from app.modules.notifications.exceptions import ChatTakenByAnother, LinkTokenInvalid
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_by_id
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.link import link_chat, stop_chat
from app.modules.notifications.services.send import answer, send_to
from app.modules.supportchat.services import write_from_telegram

logger = logging.getLogger(__name__)


def handle_update(db: Session, *, payload: dict[str, Any], now: datetime) -> str:
    """One delivery from Telegram, acted on. Returns a word for the task log.
    Every path answers: a press has ten seconds before the button gives up,
    and a command with no reply reads as a bot that is down."""
    update = read_update(payload)
    if update is None:
        return "ignored"
    known = chat_by_id(db, chat_id=update.chat_id)
    with bot() as client, override(_language(known)):
        if isinstance(update, ButtonPress):
            answer(
                client=client,
                query_id=update.query_id,
                text="Bu tugma hozircha ishlamaydi. Kabinetdan foydalaning.",
            )
            return "press_unported"
        if isinstance(update, TextMessage):
            return _typed(db, client=client, known=known, message=update, now=now)
        if isinstance(update, OtherMessage):
            return _wordless(client=client, known=known, message=update)
        return _command(db, client=client, known=known, command=update, now=now)


def _language(known: TelegramChat | None) -> str:
    return known.owner.language if known is not None else DEFAULT


def _linked(known: TelegramChat | None) -> bool:
    return known is not None and known.is_active


def _command(
    db: Session,
    *,
    client: BotClient,
    known: TelegramChat | None,
    command: Command,
    now: datetime,
) -> str:
    if command.name == COMMAND_START:
        return _start(db, client=client, known=known, command=command, now=now)
    if command.name == COMMAND_STOP:
        stop_chat(db, chat_id=command.chat_id)
        db.commit()
        _say(
            client=client,
            chat_id=command.chat_id,
            text=(
                "To'xtatildi. Xabarlar endi yuborilmaydi - hammasi kabinetda "
                "turaveradi. Qayta ulash uchun kabinetdagi tugmani bosing."
            ),
        )
        return "stopped"
    if command.name == COMMAND_HELP and known is not None and _linked(known):
        return _start_support(db, client=client, chat=known, now=now)
    _say(client=client, chat_id=command.chat_id, text=_hello(known))
    return "unknown"


def _start(
    db: Session,
    *,
    client: BotClient,
    known: TelegramChat | None,
    command: Command,
    now: datetime,
) -> str:
    """``/start <code>``; without one there is nothing to identify the
    account with - the code is issued by a signed-in cabinet."""
    if not command.argument:
        _say(client=client, chat_id=command.chat_id, text=_hello(known))
        return "no_code"
    if command.argument == RESET_PAYLOAD:
        _say(
            client=client,
            chat_id=command.chat_id,
            text=(
                "Parolni tiklash uchun yordam xizmatiga yozing - parolni "
                "tiklashga yordam beramiz."
            ),
        )
        return "reset_unported"
    try:
        chat = link_chat(
            db,
            token=command.argument,
            chat_id=command.chat_id,
            username=command.sender.username,
            now=now,
        )
    except (LinkTokenInvalid, ChatTakenByAnother) as exc:
        db.rollback()
        _say(client=client, chat_id=command.chat_id, text=exc.message)
        return "refused"
    db.commit()
    with override(chat.owner.language):
        _say(
            client=client,
            chat_id=command.chat_id,
            text=(
                "Ulandi. Endi AI takliflari, kunlik va haftalik hisobot, rad "
                "etilgan reklama shu yerga keladi. To'xtatish uchun /stop."
            ),
        )
    return "linked"


def _start_support(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> str:
    """``/yordam``: the next words typed go to Support."""
    cache.set(
        SUPPORT_WAIT_KEY.format(chat_id=chat.chat_id), 1, SUPPORT_WAIT_TTL_SECONDS
    )
    send_to(
        db,
        client=client,
        chat=chat,
        text=escaped(
            "Savolingizni shu yerga yozing — yordam xizmatiga yuboraman. "
            "Javob kelganda shu yerga xabar keladi."
        ),
        now=now,
    )
    db.commit()
    return "support_waiting"


def _typed(
    db: Session,
    *,
    client: BotClient,
    known: TelegramChat | None,
    message: TextMessage,
    now: datetime,
) -> str:
    """Private chats only: a group can never be linked to an account."""
    if message.chat_type != PRIVATE_CHAT:
        return "ignored"
    if known is not None and _linked(known):
        passed = _pass_to_support(
            db, client=client, chat=known, message=message, now=now
        )
        if passed:
            return passed
    _say(client=client, chat_id=message.chat_id, text=_hello(known))
    return "unknown"


def _pass_to_support(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    message: TextMessage,
    now: datetime,
) -> str:
    """The words after ``/yordam``, sent to Support; empty when not waiting.
    The wait ends with the first message, sent or refused."""
    key = SUPPORT_WAIT_KEY.format(chat_id=chat.chat_id)
    if not cache.get(key):
        return ""
    cache.delete(key)
    try:
        write_from_telegram(db, owner=chat.owner, body=message.text, now=now)
    except DomainError as exc:
        send_to(db, client=client, chat=chat, text=escaped(exc.message), now=now)
        db.commit()
        return "support_refused"
    send_to(
        db,
        client=client,
        chat=chat,
        text=escaped(
            "Yuborildi. Yordam xizmati javob berganda shu yerga xabar keladi."
        ),
        now=now,
        reply_to=message.message_id,
    )
    db.commit()
    return "support_sent"


def _wordless(
    *, client: BotClient, known: TelegramChat | None, message: OtherMessage
) -> str:
    if message.chat_type != PRIVATE_CHAT:
        return "ignored"
    if not _linked(known):
        _say(client=client, chat_id=message.chat_id, text=_instructions())
        return "unknown"
    _say(
        client=client,
        chat_id=message.chat_id,
        text="Hozircha faqat yozma xabarlarni o'qiyman. Matn bilan yozing.",
    )
    return "wordless"


def _hello(known: TelegramChat | None) -> str:
    if not _linked(known):
        return _instructions()
    return (
        "Siz ulangansiz.\n\n/yordam — yordam xizmatiga yozish\n"
        "/stop — xabarlarni to'xtatish"
    )


def _instructions() -> str:
    return (
        "Salom! Bu TargetologAI boti. Bu yerga reklamangiz bo'yicha xabarlar "
        "keladi. Ulash uchun kabinetga kiring va «Telegramni ulash» tugmasini "
        "bosing."
    )


def _say(*, client: BotClient, chat_id: str, text: str) -> None:
    """A reply without a stored chat to blame a failure on."""
    try:
        client.send_message(chat_id=chat_id, text=escaped(text))
    except TelegramError as exc:
        logger.info("telegram_reply_failed", extra={"reason": str(exc)})


__all__ = ["handle_update"]
