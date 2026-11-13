"""What the customer bot does when somebody writes to it.

``/start`` with a code links an account, ``/start parol`` sends a linked
one its new-password link, ``/stop`` unlinks it, ``/yordam`` points at the
support bot (or, while there is none, makes the next typed words a message
to Support), ``/hisobot``, ``/bugun`` and ``/hafta`` send
a report, and the buttons under it open a pair's figures. A stranger and an
unlinked chat get the one sentence about connecting.

``/start lc_<token>`` is the cabinet's «Telegramga uzatish»: it asks where
a pair's leads go, and the bot added to a group or a channel - or removed
from one - is read here too (``destinations.services.lead_chats``). In a
group or a channel nothing else is answered: the bot sits in lead chats.

Anything else typed in a linked chat is a question for the assistant, or the
answer to the survey question waiting there; the survey's buttons answer it,
and so does «Reklama yaxshi ishlayapti» under a frequency message (TZ 6.3),
and «Reklamani to'xtatish» and «Kuzataman» under a price rise (TZ 1.5).
Not here yet, from Django: the buttons under ad notices and under the
assistant's answers. Until they are, such a press is answered "not
available" and the answer links to the cabinet's chat.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import (
    BotClient,
    Button,
    ButtonPress,
    ChatMembership,
    Command,
    OtherMessage,
    TelegramError,
    TextMessage,
    read_update,
)

from app.common.cache import cache
from app.common.exceptions import DomainError
from app.common.i18n import DEFAULT, override
from app.modules.destinations.services.lead_chats import (
    handle_lead_chat_press,
    handle_membership,
    is_lead_chat_press,
    is_lead_chat_start,
    lead_chat_group_start,
    offer_lead_chat,
)
from app.modules.notifications.bot import bot, support_bot_configured, support_bot_home
from app.modules.notifications.constants import (
    COMMAND_HELP,
    COMMAND_REPORT,
    COMMAND_START,
    COMMAND_STOP,
    COMMAND_TODAY,
    COMMAND_WEEK,
    PRIVATE_CHAT,
    RESET_PAYLOAD,
    SUPPORT_WAIT_KEY,
    SUPPORT_WAIT_TTL_SECONDS,
)
from app.modules.notifications.exceptions import ChatTakenByAnother, LinkTokenInvalid
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_by_id
from app.modules.notifications.services.commands import (
    handle_daily_press,
    is_daily_press,
    send_today,
    send_week,
    send_yesterday,
)
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.converse import begin_conversation
from app.modules.notifications.services.frequency_press import (
    handle_frequency_press,
    is_frequency_press,
)
from app.modules.notifications.services.link import link_chat, stop_chat
from app.modules.notifications.services.password_reset import answer_reset_request
from app.modules.notifications.services.price_press import (
    handle_price_press,
    is_price_press,
)
from app.modules.notifications.services.send import answer, send_to
from app.modules.notifications.services.survey_bot import handle_survey_text
from app.modules.notifications.services.survey_press import (
    handle_survey_press,
    is_survey_press,
)
from app.modules.supportchat.constants import MessageSource
from app.modules.supportchat.drafts import Draft
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
        if isinstance(update, ChatMembership):
            return handle_membership(db, client=client, change=update, now=now)
        if isinstance(update, ButtonPress):
            # Imported here: the boards read this package's bots and chats.
            from app.modules.boards import confirm as ticket_confirm

            if is_lead_chat_press(update.data):
                return handle_lead_chat_press(db, client=client, press=update, now=now)
            if is_daily_press(update.data):
                return handle_daily_press(db, client=client, press=update, now=now)
            if is_survey_press(update.data):
                return handle_survey_press(db, client=client, press=update, now=now)
            if ticket_confirm.is_ticket_press(update.data):
                return ticket_confirm.handle_ticket_press(
                    db,
                    client=client,
                    press=update,
                    owner_id=known.owner_id
                    if known is not None and known.is_active
                    else None,
                    via=ticket_confirm.VIA_MAIN_BOT,
                    now=now,
                )
            if is_frequency_press(update.data):
                return handle_frequency_press(db, client=client, press=update, now=now)
            if is_price_press(update.data):
                return handle_price_press(db, client=client, press=update, now=now)
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
    if command.chat_type not in ("", PRIVATE_CHAT):
        if command.name == COMMAND_START and is_lead_chat_start(command.argument):
            return lead_chat_group_start(db, client=client, command=command, now=now)
        return "ignored"
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
    if known is not None and _linked(known):
        if command.name == COMMAND_HELP:
            return _start_support(db, client=client, chat=known, now=now)
        if command.name == COMMAND_REPORT:
            return send_yesterday(db, client=client, chat=known, now=now)
        if command.name == COMMAND_TODAY:
            return send_today(db, client=client, chat=known, now=now)
        if command.name == COMMAND_WEEK:
            return send_week(db, client=client, chat=known, now=now)
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
        return answer_reset_request(client=client, chat_id=command.chat_id, known=known)
    if is_lead_chat_start(command.argument):
        return offer_lead_chat(db, client=client, command=command)
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
    """``/yordam``: the support bot, where Support answers in the chat
    itself; without one, the next words typed here go to Support."""
    if support_bot_configured():
        send_to(
            db,
            client=client,
            chat=chat,
            text=escaped(
                "Yordam xizmati alohida botda: savolingizni o'sha yerga yozing - "
                "rasm, fayl va ovozli xabar ham bo'ladi, javob ham o'sha yerga keladi."
            ),
            buttons=(Button(text="Yordam botini ochish", url=support_bot_home()),),
            now=now,
        )
        db.commit()
        return "support_bot_link"
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
    """Private chats only: a group can never be linked to an account.

    Words for Support after /yordam first, then a typed answer to the survey
    question waiting in this chat, and anything else is a question for the
    assistant. An unlinked chat gets the sentence about connecting.
    """
    if message.chat_type != PRIVATE_CHAT:
        return "ignored"
    if known is not None and _linked(known):
        passed = _pass_to_support(
            db, client=client, chat=known, message=message, now=now
        )
        if passed:
            return passed
        answered = handle_survey_text(
            db, client=client, chat=known, message=message, now=now
        )
        if answered:
            return answered
    asked = begin_conversation(db, client=client, message=message, now=now)
    if asked:
        return asked
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
        write_from_telegram(
            db,
            owner=chat.owner,
            draft=Draft(body=message.text, source=MessageSource.BOT),
            now=now,
        )
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
        "Siz ulangansiz.\n\n/hisobot — kechagi hisobot\n/bugun — bugungi raqamlar\n/hafta — o'tgan hafta hisoboti\n"
        "/yordam — yordam xizmatiga yozish\n/stop — xabarlarni to'xtatish"
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
