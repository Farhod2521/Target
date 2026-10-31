"""A question typed in the bot, answered there by the assistant.

The same turn the cabinet's chat runs - the same allowance, the same thread,
the same look-ups - started where the question arrives and answered on the
``chat`` queue, where a streamed answer may hold its worker for as long as
the model takes. The webhook queue only starts it.

**Words only.** What the answer offers to do - a choice, a suggested reply -
is pressed in the cabinet's chat, which the message links to: no button
under it writes to Meta until the ads action layer is done.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session
from telegramkit import BotClient, TextMessage

from app.common.cache import cache
from app.common.exceptions import DomainError
from app.common.i18n import override
from app.modules.billing.selectors import has_live_subscription
from app.modules.chat.selectors import answer_of, newest_session, offers_on, replies_on
from app.modules.chat.services.answer import answer_turn
from app.modules.chat.services.ask import start_turn, turn_payload
from app.modules.chat.services.quota import scope_for
from app.modules.notifications.constants import ASKED_KEY, ASKED_TTL_SECONDS
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_by_id
from app.modules.notifications.services.compose import escaped, miniapp_button
from app.modules.notifications.services.send import send_to
from core.chat.telegram import render_messages

logger = logging.getLogger(__name__)


def begin_conversation(
    db: Session, *, client: BotClient, message: TextMessage, now: datetime
) -> str:
    """Start the turn for a linked chat; empty for any other, which the
    caller answers with the sentence about connecting."""
    chat = chat_by_id(db, chat_id=message.chat_id)
    if chat is None or not chat.is_active:
        return ""
    if not _first_delivery(message):
        # Telegram redelivers an update it thinks was not answered in time.
        logger.info("telegram_question_repeated", extra={"chat": message.chat_id})
        return "duplicate"
    return ask_in_chat(
        db,
        client=client,
        chat=chat,
        text=message.text,
        reply_to=message.message_id,
        now=now,
    )


def ask_in_chat(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    text: str,
    reply_to: int,
    now: datetime,
) -> str:
    owner = chat.owner
    if not has_live_subscription(db, owner=owner):
        send_to(
            db,
            client=client,
            chat=chat,
            text=escaped(
                "Obuna faol emas, shuning uchun raqamlaringiz haqida javob bera "
                "olmayman. Obunani yangilasangiz — davom etamiz."
            ),
            buttons=miniapp_button(route="billing:plans", label="Obunani yangilash"),
            now=now,
        )
        return "not_entitled"
    try:
        turn = start_turn(
            db,
            question=text,
            owner=owner,
            entitled=True,
            scope=scope_for(user_id=str(owner.id), ip="", session_key=""),
            now=now,
            session=newest_session(db, owner=owner),
        )
    except DomainError as exc:
        db.rollback()
        send_to(db, client=client, chat=chat, text=escaped(exc.message), now=now)
        return "refused"
    db.commit()
    client.send_chat_action(chat_id=chat.chat_id)
    _hand_over(turn_id=turn.turn_id, chat=chat, reply_to=reply_to)
    return "asked"


def answer_and_send(
    db: Session, *, turn_id: str, chat_id: str, reply_to: int, now: datetime
) -> str:
    """Write the answer and send it, cut where Telegram's limit falls. The
    first part replies to the question, the last carries the way to the chat
    when the answer offered something to press."""
    from app.modules.notifications.bot import bot

    payload = turn_payload(turn_id=turn_id)
    if payload is None:
        logger.info("telegram_turn_expired", extra={"turn": turn_id})
        return "expired"
    chat = chat_by_id(db, chat_id=chat_id)
    if chat is None or not chat.is_active:
        logger.info("telegram_chat_gone", extra={"turn": turn_id})
        return "gone"
    with override(chat.owner.language), bot() as client:
        client.send_chat_action(chat_id=chat.chat_id)
        answer_turn(
            db,
            turn_id=turn_id,
            payload=payload,
            now=now,
            working=lambda: client.send_chat_action(chat_id=chat.chat_id),
        )
        message_id = str(payload.get("message_id", ""))
        text = answer_of(db, owner=chat.owner, message_id=message_id)
        parts = render_messages(text) if text else []
        if not parts:
            send_to(
                db,
                client=client,
                chat=chat,
                text=escaped(
                    "Javob tayyorlanmadi. Biroz kutib, savolni qaytadan yuboring."
                ),
                now=now,
                reply_to=reply_to,
            )
            db.commit()
            return "failed"
        offered = bool(
            offers_on(db, owner=chat.owner, message_id=message_id)
            or replies_on(db, owner=chat.owner, message_id=message_id)
        )
        buttons = (
            miniapp_button(route="chat:chat", label="Chatda davom etish")
            if offered
            else ()
        )
        for index, part in enumerate(parts):
            sent = send_to(
                db,
                client=client,
                chat=chat,
                text=part,
                buttons=buttons if index == len(parts) - 1 else (),
                now=now,
                reply_to=reply_to if index == 0 else 0,
            )
            if not sent:
                db.commit()
                return "undelivered"
    db.commit()
    return "answered"


def _first_delivery(message: TextMessage) -> bool:
    return bool(
        cache.add(
            ASKED_KEY.format(chat_id=message.chat_id, message_id=message.message_id),
            1,
            ASKED_TTL_SECONDS,
        )
    )


def _hand_over(*, turn_id: str, chat: TelegramChat, reply_to: int) -> None:
    from app.modules.notifications.tasks import answer_for_telegram

    answer_for_telegram.delay(turn_id, chat.chat_id, reply_to)


__all__ = ["answer_and_send", "ask_in_chat", "begin_conversation"]
