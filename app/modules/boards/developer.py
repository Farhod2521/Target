"""A Support ticket handed to the Developers, and closed when they fix it.

«Dasturchiga berish» keeps a fault on the Developer page (``report_fault``,
subject ``ticket:<card id>``): Support's words, the ticket's open problems
with Meta's own text, and who handed it over. The staff bot tells the
Engineers as with any fault of ours, and its 6-letter number is written on
the ticket's line. The same client's ticket handed over again while that
fault is open counts on it.

When a Developer settles that fault («Hal qilindi» on the Developer page),
the ticket closes: its open problems are solved by the Developer and it
goes to Hal qilindi, and its person is told (``notices``). A ticket Support
took back to work meanwhile stays where it is, with a line saying it was
fixed.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.hooks import on
from app.modules.accounts.models import User
from app.modules.audit.services.faults import SETTLED_HOOK, report_fault
from app.modules.boards import reasons
from app.modules.boards.constants import Board, EventKind, SupportColumn
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.services import move, record

logger = logging.getLogger(__name__)

CODE: Final = "support_ticket"
WHERE: Final = "support:developer"
SUBJECT: Final = "ticket:"
FIXED_NOTE: Final = "Dasturchi tuzatdi"


def hand_over(
    db: Session, *, card: BoardCard, note: str, by: User, now: datetime
) -> str:
    """Keep the fault for the Developers; its reference, or "" when it
    could not be kept. Writes the reference on the ticket's line. Commits."""
    problems = [
        {
            "kind": item.get("code", ""),
            "detail": item.get("detail", ""),
            **({"meta": item["raw"]} if item.get("raw") else {}),
            **({"target": item["target"]} if item.get("target") else {}),
            "at": item.get("at", ""),
        }
        for item in reasons.open_reasons(card)
    ]
    words = "; ".join(p["detail"] for p in problems if p["detail"])
    reference = report_fault(
        db,
        owner_id=card.owner_id,
        code=CODE,
        message=f"Support: {note}" + (f" · Muammo: {words}" if words else ""),
        where=WHERE,
        subject=f"{SUBJECT}{card.id}",
        context={
            "ticket": str(card.id),
            "support": by.full_name or by.email,
            "note": note,
            "problems": problems,
        },
        now=now,
    )
    if not reference:
        return ""
    line = db.scalar(
        select(BoardCardEvent)
        .where(
            BoardCardEvent.card_id == card.id,
            BoardCardEvent.kind == str(EventKind.DEVELOPER),
        )
        .order_by(BoardCardEvent.created_at.desc())
        .limit(1)
    )
    if line is not None and reference not in line.body:
        line.body = f"{line.body} · Xato raqami: {reference}".lstrip(" ·")
        db.commit()
    return reference


@on(SETTLED_HOOK)
def close_fixed_ticket(
    *, db: Session, path: str, by_id: uuid.UUID, now: datetime, **_: Any
) -> None:
    """The fault settled: the ticket it came from closes. Commits. A ticket
    that cannot be closed is logged: the fault stays settled either way."""
    if not path.startswith(SUBJECT):
        return
    try:
        card_id = uuid.UUID(path[len(SUBJECT) :])
    except ValueError:
        return
    try:
        _close(db, card_id=card_id, by_id=by_id, now=now)
    except Exception:
        db.rollback()
        logger.exception("fixed_ticket_not_closed", extra={"card_id": str(card_id)})


def _close(db: Session, *, card_id: uuid.UUID, by_id: uuid.UUID, now: datetime) -> None:
    card = db.scalar(
        select(BoardCard)
        .where(BoardCard.id == card_id, BoardCard.board == str(Board.SUPPORT))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    developer = db.get(User, by_id)
    if card is None or developer is None:
        return
    if card.column_code != SupportColumn.DEVELOPER:
        record(db, card=card, kind=EventKind.DEV_FIXED, now=now, actor=developer)
        db.commit()
        return
    reasons.solve_open(card, by=developer, note=FIXED_NOTE, now=now)
    card.closed_at = now
    card.due_at = None
    move(
        db,
        card=card,
        to=str(SupportColumn.RESOLVED),
        kind=EventKind.DEV_FIXED,
        now=now,
        actor=developer,
    )
    db.commit()
