"""The ticket's person told in the staff bot when their ticket needs them.

What is told: the ticket given to them (by the Owner, or with the chat),
the wait over, the time to call again come, the client writing back, the
client saying it is not solved, a new problem on a ticket they hold, the
ticket opened again for them, and the Developer fixing it.
Nothing they did themselves, and nothing on a ticket with nobody on it.

The minute sweep reads the lines not told yet, at most an hour old (a line
older than that is no news), and marks each once, told or not, so nothing
goes twice. One message a ticket a sweep, its lines together. A person
without the staff bot linked is not told; the board shows it anyway.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import TelegramError

from app.modules.accounts.models import User
from app.modules.boards.constants import SWEEP_BATCH, Board, EventKind
from app.modules.boards.models import BoardCard, BoardCardEvent

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
