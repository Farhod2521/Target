"""What office people are told in the staff bot, so a card is not
forgotten while the board is closed.

Support — the ticket's person, when their ticket needs them: the ticket
given to them (by the Owner, or with the chat), the wait over, the time to
call again come, the client writing back, the client saying it is not
solved, a new problem on a ticket they hold, the ticket opened again for
them, and the Developer fixing it. Nothing they did themselves, and nothing
on a ticket with nobody on it. The minute sweep reads the lines not told
yet, at most an hour old (a line older than that is no news), and marks
each once, told or not, so nothing goes twice. One message a ticket a
sweep, its lines together.

Sales (``sweep``):

- a card's time («Vaqt qo'yish», «Bog'lanib bo'lmadi» with a time) has
  come: its person, once per time set;
- the client opened a plan bill: the card's person, once per bill;
- new leads wait in Ishlanmagan: the Sales team, at most every half hour
  and in the office's working hours only.

Each Sales fact to a person is written on the card as a history line with
its own ``ref``, so a second run never tells it twice. Whoever has not tied
the staff bot is skipped and told nothing later about it.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Final

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
    QUEUE_NOTICE_MINUTES,
    SALES_COLUMN_LABELS,
    SWEEP_BATCH,
    WORK_HOURS,
    Board,
    EventKind,
    SalesColumn,
)
from app.modules.boards.models import BoardCard, BoardCardEvent, BoardColumn
from app.modules.boards.services import record

logger = logging.getLogger(__name__)

NOTICE_KINDS: Final = frozenset(
    {
        str(EventKind.ASSIGNED),
        str(EventKind.CHAT_HANDED),
        str(EventKind.WAIT_OVER),
        str(EventKind.CLIENT_REPLIED),
        str(EventKind.DENIED),
        str(EventKind.REASON),
        str(EventKind.REOPENED),
        str(EventKind.DEV_FIXED),
        str(EventKind.CALL_AGAIN),
    }
)
# A line older than this when the sweep meets it is not news any more.
NOTICE_FRESH: Final = timedelta(hours=1)
BODY_MAX: Final = 200


def _line(kind: str, body: str, actor: User | None) -> str:
    from app.modules.notifications.services.compose import escaped

    who = f" ({escaped(actor.full_name or actor.email)})" if actor else ""
    said = escaped(" ".join(body.split())[:BODY_MAX])
    if kind in (EventKind.ASSIGNED, EventKind.CHAT_HANDED):
        return f"Zayavka sizga berildi{who}."
    if kind == EventKind.WAIT_OVER:
        return "Kutish vaqti tugadi: zayavka «Ishlanmoqda»ga qaytdi."
    if kind == EventKind.CLIENT_REPLIED:
        return "Mijoz chatga yozdi: zayavka «Ishlanmoqda»ga qaytdi."
    if kind == EventKind.DENIED:
        return "Mijoz «hal bo'lmadi» dedi: zayavka sizga qaytdi."
    if kind == EventKind.CALL_AGAIN:
        return "Qayta qo'ng'iroq vaqti keldi: zayavka «Ishlanmoqda»ga qaytdi."
    if kind == EventKind.DEV_FIXED:
        return f"Dasturchi tuzatdi{who}: zayavka yopildi."
    if kind == EventKind.REASON:
        return f"Yangi muammo: {said}" if said else "Yangi muammo keldi."
    return f"Zayavka qayta ochildi{who}." + (f" {said}" if said else "")


def _text(client: User, card_id: uuid.UUID, lines: list[str]) -> str:
    from app.modules.notifications.services.compose import _bold, _link

    head = _bold(f"Zayavka: {client.full_name or client.email}")
    body = "\n".join(f"• {line}" for line in lines)
    link = _link(path=f"/ofis/kanban/support/?karta={card_id}", label="Kanbanda ochish")
    return f"{head}\n{body}\n\n{link}"


def tell_ticket_people(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """Tell each ticket's person of the lines not told yet. How many
    messages went out."""
    from app.modules.notifications.bot import staff_bot, staff_bot_configured
    from app.modules.notifications.selectors import staff_chat_for

    rows = list(
        db.execute(
            select(BoardCardEvent, BoardCard)
            .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
            .where(
                BoardCard.board == str(Board.SUPPORT),
                BoardCardEvent.kind.in_(NOTICE_KINDS),
                BoardCardEvent.noticed_at.is_(None),
                BoardCardEvent.created_at >= now - NOTICE_FRESH,
            )
            .order_by(BoardCardEvent.created_at)
            .limit(limit)
            .with_for_update(of=BoardCardEvent, skip_locked=True)
            # The card as it is now: who holds it decides who is told.
            .execution_options(populate_existing=True)
        )
    )
    if not rows:
        return 0
    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[BoardCardEvent]] = defaultdict(list)
    cards: dict[uuid.UUID, BoardCard] = {}
    for event, card in rows:
        event.noticed_at = now
        holder = card.manager_id
        # Nobody holds it (a new round for the queue), or it is their own doing.
        if holder is None or event.actor_id == holder:
            continue
        grouped[(card.id, holder)].append(event)
        cards[card.id] = card
    sent = 0
    if grouped and staff_bot_configured():
        with staff_bot() as client:
            for (card_id, person_id), events in grouped.items():
                member = db.get(User, person_id)
                chat = staff_chat_for(db, owner=member) if member else None
                if chat is None:
                    continue
                owner = db.get(User, cards[card_id].owner_id)
                if owner is None:
                    continue
                lines = [
                    _line(
                        e.kind, e.body, db.get(User, e.actor_id) if e.actor_id else None
                    )
                    for e in events
                ]
                # The same line twice (a refused press repeated) is said once.
                lines = list(dict.fromkeys(lines))
                try:
                    client.send_message(
                        chat_id=chat.chat_id, text=_text(owner, card_id, lines)
                    )
                    sent += 1
                except TelegramError as exc:
                    logger.info("ticket_notice_failed", extra={"reason": str(exc)})
    db.commit()
    return sent


# --- Sales ---

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


def _code_label(code: str) -> str:
    """A column's name as the code has it; none for one the code lacks."""
    if code not in SalesColumn.values:
        return ""
    return str(SALES_COLUMN_LABELS[SalesColumn(code)])


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
    # The column as the board names it now: the superuser renames columns
    # and adds their own.
    names: dict[str, str] = (
        {
            code: name
            for code, name in db.execute(
                select(BoardColumn.code, BoardColumn.name).where(
                    BoardColumn.board == str(Board.SALES)
                )
            )
        }
        if cards
        else {}
    )
    sent = 0
    for card in cards:
        chat = chats.get(card.manager_id) if card.manager_id else None
        if chat is None or card.due_at is None:
            continue
        column = names.get(card.column_code) or _code_label(card.column_code)
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
    from app.modules.boards.sales_kinds import waiting as waiting_now

    # What «Lid olish» may give: Ishlanmagan with nobody on it.
    waiting = waiting_now()
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
