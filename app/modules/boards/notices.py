"""What the Sales team is told on Telegram (the staff bot), so a card is
not forgotten while the board is closed:

- a card's time («Vaqt qo'yish», «Bog'lanib bo'lmadi» with a time) has
  come: its person, once per time set;
- the client opened a plan bill: the card's person, once per bill;
- new leads wait in Ishlanmagan: the Sales team, at most every half hour
  and in the office's working hours only.

Each fact to a person is written on the card as a history line with its own
``ref``, so a second run never tells it twice. Whoever has not tied the
staff bot is skipped and told nothing later about it.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session
from telegramkit import BotClient, Button, TelegramError

from app.common.cache import cache
from app.common.config import settings
from app.common.dates import localtime
from app.modules.accounts.models import User
from app.modules.billing.models import Invoice
from app.modules.boards.access import works_on
from app.modules.boards.constants import (
    DUE_REMIND_WINDOW_MINUTES,
    OFFER_COLUMNS,
    QUEUE_NOTICE_MINUTES,
    SALES_COLUMN_LABELS,
    SWEEP_BATCH,
    WORK_HOURS,
    Board,
    EventKind,
    SalesColumn,
)
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.services import record

logger = logging.getLogger(__name__)

QUEUE_TOLD_KEY = "boards:sales:queue_told_at"
SALES_BOARD_PATH = "/ofis/kanban/sotuv/"


def due_ref(due_at: datetime) -> str:
    return f"due:{localtime(due_at, 'UTC').strftime('%Y%m%d%H%M')}"


def card_url(card: BoardCard) -> str:
    return f"{settings.site_url}{SALES_BOARD_PATH}?karta={card.id}"


def _chats(db: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    from app.modules.notifications.models import StaffChat

    if not user_ids:
        return {}
    return {
        owner: chat
        for owner, chat in db.execute(
            select(StaffChat.owner_id, StaffChat.chat_id).where(
                StaffChat.owner_id.in_(user_ids), StaffChat.is_active.is_(True)
            )
        )
    }


def _send(client: BotClient, *, chat_id: str, text: str, url: str = "") -> bool:
    buttons = (Button(text="Kartani ochish", url=url),) if url else ()
    try:
        client.send_message(chat_id=chat_id, text=text, buttons=buttons)
    except TelegramError:
        logger.warning("sales notice not delivered", extra={"chat_id": chat_id})
        return False
    return True


def _who(card: BoardCard) -> str:
    from app.modules.notifications.services.compose import escaped

    owner = card.owner
    name = escaped(owner.full_name or owner.email)
    phone = f"\n📞 {escaped(owner.phone)}" if owner.phone else ""
    return f"<b>{name}</b>{phone}"


def remind_due(
    db: Session, *, client: BotClient, now: datetime, limit: int = SWEEP_BATCH
) -> int:
    """Cards whose time came within the window: told to their person."""
    # The same words the line is written with: the time in UTC to the minute.
    ref = func.concat(
        "due:", func.to_char(func.timezone("UTC", BoardCard.due_at), "YYYYMMDDHH24MI")
    )
    told = exists().where(
        BoardCardEvent.card_id == BoardCard.id, BoardCardEvent.ref == ref
    )
    cards = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == str(Board.SALES),
                BoardCard.closed_at.is_(None),
                BoardCard.manager_id.is_not(None),
                BoardCard.due_at <= now,
                BoardCard.due_at > now - timedelta(minutes=DUE_REMIND_WINDOW_MINUTES),
                ~told,
            )
            .order_by(BoardCard.due_at)
            .limit(limit)
        )
    )
    chats = _chats(db, {card.manager_id for card in cards if card.manager_id})
    sent = 0
    for card in cards:
        chat = chats.get(card.manager_id) if card.manager_id else None
        if chat is None or card.due_at is None:
            continue
        column = SALES_COLUMN_LABELS.get(SalesColumn(card.column_code), "")
        at = localtime(card.due_at).strftime("%H:%M")
        text = f"⏰ Qo'ng'iroq vaqti keldi ({at})\n{_who(card)}\nUstun: {column}"
        if not _send(client, chat_id=chat, text=text, url=card_url(card)):
            continue
        record(
            db,
            card=card,
            kind=EventKind.DUE_REMINDED,
            now=now,
            ref=due_ref(card.due_at),
        )
        db.commit()
        sent += 1
    return sent


def tell_bills(
    db: Session, *, client: BotClient, now: datetime, limit: int = SWEEP_BATCH
) -> int:
    """A client somebody works opened a plan bill: their person calls now,
    while the client is at the payment page."""
    from app.modules.boards.view import open_bills

    bills = open_bills(now).subquery()
    told = exists().where(
        BoardCardEvent.card_id == BoardCard.id,
        BoardCardEvent.ref == func.concat("told:", bills.c.id),
    )
    rows = list(
        db.execute(
            select(BoardCard, bills.c.id)
            .join(bills, bills.c.owner_id == BoardCard.owner_id)
            .where(
                BoardCard.board == str(Board.SALES),
                BoardCard.closed_at.is_(None),
                BoardCard.manager_id.is_not(None),
                bills.c.created_at > now - timedelta(minutes=DUE_REMIND_WINDOW_MINUTES),
                ~told,
            )
            .order_by(bills.c.created_at)
            .limit(limit)
        )
    )
    chats = _chats(db, {card.manager_id for card, _ in rows if card.manager_id})
    sent = 0
    for card, bill_id in rows:
        chat = chats.get(card.manager_id) if card.manager_id else None
        if chat is None:
            continue
        bill = db.get(Invoice, bill_id)
        plan = f" («{bill.plan.name}»)" if bill is not None and bill.plan else ""
        text = f"💳 Mijoz to'lov hisobini ochdi{plan}\n{_who(card)}\nHozir qo'ng'iroq qiling."
        if not _send(client, chat_id=chat, text=text, url=card_url(card)):
            continue
        record(db, card=card, kind=EventKind.BILL_TOLD, now=now, ref=f"told:{bill_id}")
        db.commit()
        sent += 1
    return sent


def tell_queue(db: Session, *, client: BotClient, now: datetime) -> int:
    """New leads wait: the Sales team hears how many, in working hours and
    at most every ``QUEUE_NOTICE_MINUTES``. Only leads opened since the last
    word count as new."""
    hour = localtime(now).hour
    if not WORK_HOURS[0] <= hour < WORK_HOURS[1]:
        return 0
    last = cache.get(QUEUE_TOLD_KEY)
    last_at = datetime.fromisoformat(last) if isinstance(last, str) else None
    if last_at is not None and now - last_at < timedelta(minutes=QUEUE_NOTICE_MINUTES):
        return 0
    # What «Lid olish» may give: Ishlanmagan, and a Start buyer's discount
    # running with nobody on it.
    waiting = (
        BoardCard.board == str(Board.SALES),
        BoardCard.closed_at.is_(None),
        BoardCard.manager_id.is_(None),
        BoardCard.column_code.in_([str(SalesColumn.UNWORKED), *OFFER_COLUMNS]),
    )
    total = int(db.scalar(select(func.count()).where(*waiting)) or 0)
    since = last_at or now - timedelta(minutes=QUEUE_NOTICE_MINUTES)
    fresh = int(
        db.scalar(select(func.count()).where(*waiting, BoardCard.created_at > since))
        or 0
    )
    if not fresh:
        return 0
    cache.set(QUEUE_TOLD_KEY, now.isoformat(), QUEUE_NOTICE_MINUTES * 60 * 4)
    team = [
        person
        for person in db.scalars(
            select(User).where(User.is_staff.is_(True), User.is_active.is_(True))
        )
        if works_on(db, person, Board.SALES)
    ]
    chats = _chats(db, {person.id for person in team})
    text = (
        f"🆕 {fresh} ta yangi lid keldi. Navbatda jami {total} ta.\n"
        "Kanbanda «Lid olish»ni bosing: eng issig'i birinchi beriladi."
    )
    url = f"{settings.site_url}{SALES_BOARD_PATH}"
    return sum(
        _send(client, chat_id=chat, text=text, url=url) for chat in chats.values()
    )


def sweep(db: Session, *, now: datetime) -> dict[str, Any]:
    from app.modules.notifications.bot import staff_bot, staff_bot_configured

    if not staff_bot_configured():
        return {"due": 0, "bills": 0, "queue": 0}
    with staff_bot() as client:
        return {
            "due": remind_due(db, client=client, now=now),
            "bills": tell_bills(db, client=client, now=now),
            "queue": tell_queue(db, client=client, now=now),
        }
