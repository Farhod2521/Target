"""What moves cards on its own. Each rule reads the database since the
board went live and writes each fact once, so running it again changes
nothing."""

from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceKind, InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Subscription
from app.modules.boards.constants import SWEEP_BATCH, Board, EventKind, SalesColumn
from app.modules.boards.models import BoardCard
from app.modules.boards.selectors import ensure_board, live_since
from app.modules.boards.services import move, record

# Paid once already: such a client is not a first-time sign-up.
_PAID_BEFORE = (str(InvoiceStatus.PAID), str(InvoiceStatus.REFUNDED))


def open_leads(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A Sales card in Ishlanmagan for everybody who signed up after the
    board went live and has not paid. Staff, CRM logins and blocked
    accounts are not leads; nor is an account given a running plan."""
    since = live_since(db, board=Board.SALES)
    if since is None:
        return 0
    paid = exists().where(Invoice.owner_id == User.id, Invoice.status.in_(_PAID_BEFORE))
    running = exists().where(
        Subscription.owner_id == User.id,
        Subscription.status == str(SubscriptionStatus.ACTIVE),
    )
    carded = exists().where(
        BoardCard.owner_id == User.id, BoardCard.board == str(Board.SALES)
    )
    people = list(
        db.scalars(
            select(User)
            .where(
                User.date_joined >= since,
                User.crm_owner_id.is_(None),
                User.is_staff.is_(False),
                User.is_superuser.is_(False),
                User.is_active.is_(True),
                ~paid,
                ~running,
                ~carded,
            )
            .order_by(User.date_joined, User.id)
            .limit(limit)
        )
    )
    for person in people:
        card = BoardCard(
            board=str(Board.SALES),
            owner_id=person.id,
            column_code=str(SalesColumn.UNWORKED),
            opened_at=person.date_joined,
            column_since=now,
            reasons=[],
        )
        db.add(card)
        db.flush()
        record(
            db,
            card=card,
            kind=EventKind.OPENED,
            now=now,
            to_column=card.column_code,
            ref="opened",
        )
    db.commit()
    return len(people)


def mark_sold(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A Sales card whose client paid a plan goes to Sotildi from any
    column, Yopildi too: the payment is what happened."""
    first_paid = (
        select(Invoice.owner_id, func.min(Invoice.paid_at).label("paid_at"))
        .where(
            Invoice.status == str(InvoiceStatus.PAID),
            Invoice.kind == str(InvoiceKind.PLAN),
        )
        .group_by(Invoice.owner_id)
        .subquery()
    )
    rows = list(
        db.execute(
            select(BoardCard, first_paid.c.paid_at)
            .join(first_paid, first_paid.c.owner_id == BoardCard.owner_id)
            .where(
                BoardCard.board == str(Board.SALES),
                BoardCard.column_code != str(SalesColumn.SOLD),
            )
            .order_by(BoardCard.opened_at)
            .limit(limit)
            .with_for_update(of=BoardCard, skip_locked=True)
        )
    )
    for card, paid_at in rows:
        card.closed_at = paid_at or now
        card.close_reason = ""
        move(
            db,
            card=card,
            to=str(SalesColumn.SOLD),
            kind=EventKind.SOLD,
            now=now,
            ref="sold",
        )
    db.commit()
    return len(rows)


def sweep_sales(db: Session, *, now: datetime) -> tuple[int, int]:
    ensure_board(db, board=Board.SALES, now=now)
    db.commit()
    return open_leads(db, now=now), mark_sold(db, now=now)
