"""«Muammoyingiz hal bo'ldimi?»: a ticket Support called solved is closed by
its client. The question goes to the support bot, to the main bot when that
one is not linked, and stands in the cabinet either way; a yes closes the
ticket, a no gives it back to its person, and silence closes it after a day."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import exists, select
from sqlalchemy.orm import Session
from telegramkit import BotClient, Button, ButtonPress, TelegramError

from app.modules.boards.constants import (
    CONFIRM_HOURS,
    SWEEP_BATCH,
    Board,
    EventKind,
    SupportColumn,
)
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.services import move, record
from app.modules.notifications.bot import (
    bot,
    is_configured,
    support_bot,
    support_bot_configured,
)
from app.modules.notifications.models import SupportBotChat, TelegramChat
from app.modules.notifications.services.send import answer as answer_press
from app.modules.notifications.services.send import edit

logger = logging.getLogger(__name__)

PRESS: Final = "tk"
QUESTION: Final = (
    "Murojaatingiz bo'yicha ish yakunlandi.\n\n<b>Muammoyingiz hal bo'ldimi?</b>"
)
SOLVED_WORDS: Final = "Rahmat! Murojaatingiz yopildi."
REOPENED_WORDS: Final = (
    "Tushunarli, murojaatingiz qayta ochildi. Mutaxassis siz bilan bog'lanadi. "
    "Nima hal bo'lmaganini yozib qoldirsangiz, tezroq yordam beramiz."
)
STALE_WORDS: Final = "Bu savolga javob berilgan."

# Where the answer came from, as the card's history says it.
VIA_SUPPORT_BOT: Final = "Support botda"
VIA_MAIN_BOT: Final = "Telegram botda"
VIA_SITE: Final = "Saytda"

SOLVED: Final = "solved"
REOPENED: Final = "reopened"
STALE: Final = "stale"


def stamp_of(card: BoardCard) -> int:
    """Which asking this is: a ticket solved twice is asked twice, and a
    button under the first question does not answer the second."""
    return int(card.column_since.timestamp())


def press_data(card: BoardCard, *, solved: bool) -> str:
    return f"{PRESS}:{'y' if solved else 'n'}:{card.id.hex}:{stamp_of(card)}"


def read_press(data: str) -> tuple[bool, uuid.UUID, int] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != PRESS or parts[1] not in ("y", "n"):
        return None
    try:
        return parts[1] == "y", uuid.UUID(hex=parts[2]), int(parts[3])
    except ValueError:
        return None


def is_ticket_press(data: str) -> bool:
    return read_press(data) is not None


def pending(db: Session, *, owner_id: uuid.UUID) -> BoardCard | None:
    """The client's ticket, if it waits for their answer."""
    return db.scalar(
        select(BoardCard).where(
            BoardCard.board == str(Board.SUPPORT),
            BoardCard.owner_id == owner_id,
            BoardCard.column_code == str(SupportColumn.CONFIRMING),
        )
    )


def expires_at(card: BoardCard) -> datetime:
    return card.column_since + timedelta(hours=CONFIRM_HOURS)


def answer(
    db: Session,
    *,
    owner_id: uuid.UUID,
    solved: bool,
    via: str,
    now: datetime,
    stamp: int | None = None,
) -> str:
    """The client's yes or no. Yes: Hal qilindi. No: back to its person in
    Ishlanmoqda, over their limit too, or to Yangi if it has nobody. An
    answer to a question no longer asked changes nothing."""
    card = db.scalar(
        select(BoardCard)
        .where(BoardCard.board == str(Board.SUPPORT), BoardCard.owner_id == owner_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        card is None
        or card.column_code != SupportColumn.CONFIRMING
        or (stamp is not None and stamp != stamp_of(card))
    ):
        db.rollback()
        return STALE
    card.due_at = None
    if solved:
        card.closed_at = now
        move(
            db,
            card=card,
            to=str(SupportColumn.RESOLVED),
            kind=EventKind.CONFIRMED,
            now=now,
            body=via,
        )
        db.commit()
        return SOLVED
    to = SupportColumn.IN_PROGRESS if card.manager_id else SupportColumn.NEW
    move(db, card=card, to=str(to), kind=EventKind.DENIED, now=now, body=via)
    db.commit()
    return REOPENED


def _buttons(card: BoardCard) -> tuple[Button, ...]:
    return (
        Button(text="Ha, hal bo'ldi", data=press_data(card, solved=True)),
        Button(text="Yo'q", data=press_data(card, solved=False)),
    )


def _send(db: Session, *, card: BoardCard) -> str:
    """The question into the client's Telegram: the support bot, else the
    main bot. Where it went, for the history; the cabinet shows it anyway."""
    if support_bot_configured():
        chat_id = db.scalar(
            select(SupportBotChat.chat_id).where(
                SupportBotChat.owner_id == card.owner_id,
                SupportBotChat.is_active.is_(True),
            )
        )
        if chat_id:
            try:
                with support_bot() as client:
                    client.send_message(
                        chat_id=chat_id, text=QUESTION, buttons=_buttons(card)
                    )
                return "Support botga yuborildi."
            except TelegramError as exc:
                logger.info("ticket_question_failed", extra={"reason": str(exc)})
    if is_configured():
        chat_id = db.scalar(
            select(TelegramChat.chat_id).where(
                TelegramChat.owner_id == card.owner_id,
                TelegramChat.is_active.is_(True),
            )
        )
        if chat_id:
            try:
                with bot() as client:
                    client.send_message(
                        chat_id=chat_id, text=QUESTION, buttons=_buttons(card)
                    )
                return "Telegram botga yuborildi."
            except TelegramError as exc:
                logger.info("ticket_question_failed", extra={"reason": str(exc)})
    return "Telegram ulanmagan: savol faqat saytda."


def ask_clients(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """Every ticket that entered Tasdiq kutilmoqda and was not asked yet.
    Each asking once: the line it writes is the mark."""
    asked = exists().where(
        BoardCardEvent.card_id == BoardCard.id,
        BoardCardEvent.kind == str(EventKind.ASKED),
        BoardCardEvent.created_at >= BoardCard.column_since,
    )
    cards = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == str(Board.SUPPORT),
                BoardCard.column_code == str(SupportColumn.CONFIRMING),
                ~asked,
            )
            .order_by(BoardCard.column_since)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card in cards:
        where = _send(db, card=card)
        record(
            db,
            card=card,
            kind=EventKind.ASKED,
            # Never before the ticket entered the column: a press that
            # landed after this run began must still read as asked.
            now=max(now, card.column_since),
            body=where,
            ref=f"ask:{stamp_of(card)}",
        )
    db.commit()
    return len(cards)


def close_unanswered(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A day without the client's answer: the ticket goes to Yopildi."""
    cards = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == str(Board.SUPPORT),
                BoardCard.column_code == str(SupportColumn.CONFIRMING),
                BoardCard.column_since <= now - timedelta(hours=CONFIRM_HOURS),
            )
            .order_by(BoardCard.column_since)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card in cards:
        card.closed_at = now
        card.due_at = None
        move(
            db,
            card=card,
            to=str(SupportColumn.CLOSED),
            kind=EventKind.UNANSWERED,
            now=now,
        )
    db.commit()
    return len(cards)


def handle_ticket_press(
    db: Session,
    *,
    client: BotClient,
    press: ButtonPress,
    owner_id: uuid.UUID | None,
    via: str,
    now: datetime,
) -> str:
    """«Ha» or «Yo'q» under the question, in either bot. ``owner_id`` is
    whose chat the press came from: a forwarded question keeps its buttons,
    and only the ticket's own client answers it."""
    parsed = read_press(press.data)
    if parsed is None:  # pragma: no cover - routed here only when it parses
        return "unreadable"
    solved, card_id, stamp = parsed
    card = db.get(BoardCard, card_id)
    if card is None or owner_id is None or card.owner_id != owner_id:
        answer_press(
            client=client,
            query_id=press.query_id,
            text="Bu tugma sizga tegishli emas.",
            alert=True,
        )
        return "ticket_stranger"
    result = answer(db, owner_id=owner_id, solved=solved, via=via, now=now, stamp=stamp)
    words = {SOLVED: SOLVED_WORDS, REOPENED: REOPENED_WORDS}.get(result, STALE_WORDS)
    edit(
        client=client,
        chat_id=press.chat_id,
        message_id=press.message_id,
        text=words,
    )
    answer_press(client=client, query_id=press.query_id)
    return f"ticket_{result}"
