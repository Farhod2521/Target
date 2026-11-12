"""Support tickets: one per client, for every reason. A new reason on a
solved ticket reopens it with the same person, so one Support member keeps
working with the client."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.boards.constants import Board, EventKind, SupportColumn, TicketReason
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.services import move, record


def _locked(db: Session, owner_id: uuid.UUID) -> BoardCard | None:
    return db.scalar(
        select(BoardCard)
        .where(BoardCard.board == str(Board.SUPPORT), BoardCard.owner_id == owner_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def raise_ticket(
    db: Session,
    *,
    owner_id: uuid.UUID,
    reason: TicketReason,
    ref: str,
    now: datetime,
    detail: str = "",
    actor: User | None = None,
) -> bool:
    """Put ``reason`` on the client's ticket, opening or reopening it.
    ``ref`` names the fact (a payment, a launch); the same fact twice is
    nothing. ``actor`` is who opened it by hand; a rule has none. Whether anything was written. The caller commits."""
    item = {"code": str(reason), "ref": ref, "at": now.isoformat(), "detail": detail}
    card = _locked(db, owner_id)
    if card is None:
        # Two rules opening the same client's ticket at once meet the
        # one-ticket index: the second finds the first one's card.
        opened = db.scalar(
            insert(BoardCard)
            .values(
                id=uuid.uuid4(),
                created_at=now,
                updated_at=now,
                board=str(Board.SUPPORT),
                owner_id=owner_id,
                column_code=str(SupportColumn.NEW),
                opened_at=now,
                column_since=now,
                reasons=[item],
            )
            .on_conflict_do_nothing(index_elements=["board", "owner_id"])
            .returning(BoardCard.id)
        )
        card = _locked(db, owner_id)
        assert card is not None
        if opened is not None:
            record(
                db,
                card=card,
                kind=EventKind.TICKET,
                now=now,
                to_column=card.column_code,
                body=detail,
                ref=ref,
                actor=actor,
            )
            db.flush()
            return True
    if db.scalar(
        select(BoardCardEvent.id).where(
            BoardCardEvent.card_id == card.id, BoardCardEvent.ref == ref
        )
    ):
        return False
    card.reasons = [*card.reasons, item]
    if card.column_code == SupportColumn.RESOLVED:
        card.closed_at = None
        to = SupportColumn.IN_PROGRESS if card.manager_id else SupportColumn.NEW
        move(
            db,
            card=card,
            to=str(to),
            kind=EventKind.REOPENED,
            now=now,
            body=detail,
            ref=ref,
            actor=actor,
        )
    else:
        record(
            db,
            card=card,
            kind=EventKind.REASON,
            now=now,
            body=detail,
            ref=ref,
            actor=actor,
        )
    # Flushed, so the same fact met again in this transaction is seen.
    db.flush()
    return True
