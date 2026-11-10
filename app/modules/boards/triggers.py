"""What moves cards on its own. Each rule reads the database since the
board went live and writes each fact once, so running it again changes
nothing."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import LaunchStatus
from app.modules.ads.models import CampaignLaunch
from app.modules.audit.constants import ActionStatus, ActorType
from app.modules.audit.models import ActionLog
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceKind,
    InvoiceStatus,
    SubscriptionStatus,
)
from app.modules.billing.models import Invoice, Subscription
from app.modules.boards.constants import (
    NOT_META_ERRORS,
    SETUP_GRACE_MINUTES,
    SWEEP_BATCH,
    Board,
    EventKind,
    SalesColumn,
    TicketReason,
)
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.selectors import ensure_board, live_since
from app.modules.boards.services import move, record
from app.modules.boards.tickets import raise_ticket

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
            .execution_options(populate_existing=True)
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


def _since(db: Session) -> datetime | None:
    return live_since(db, board=Board.SUPPORT)


def setup_late(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """Paid a plan an hour ago or more and still not set up. One fact per
    payment, so a renewal that finds the setup undone counts again."""
    since = _since(db)
    if since is None:
        return 0
    rows = list(
        db.execute(
            select(Invoice.id, Invoice.owner_id)
            .join(Subscription, Subscription.owner_id == Invoice.owner_id)
            .where(
                Invoice.status == str(InvoiceStatus.PAID),
                Invoice.kind == str(InvoiceKind.PLAN),
                Invoice.paid_at >= since,
                Invoice.paid_at <= now - timedelta(minutes=SETUP_GRACE_MINUTES),
                Subscription.status.in_([str(s) for s in LIVE_SUBSCRIPTION_STATUSES]),
                Subscription.setup_completed_at.is_(None),
                ~_has_ref(Invoice.owner_id, func.concat("setup:", Invoice.id)),
            )
            .order_by(Invoice.paid_at)
            .limit(limit)
        )
    )
    written = sum(
        raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.SETUP,
            ref=f"setup:{invoice_id}",
            now=now,
            detail="To'lovdan 1 soat o'tdi, sozlash tugamagan.",
        )
        for invoice_id, owner_id in rows
        if owner_id is not None
    )
    db.commit()
    return written


def from_sales(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A client Sales marked «Support kerak» paid: the ticket opens now,
    not an hour later."""
    if _since(db) is None:
        return 0
    rows = list(
        db.execute(
            select(BoardCard.id, BoardCard.owner_id)
            .where(
                BoardCard.board == str(Board.SALES),
                BoardCard.column_code == str(SalesColumn.SOLD),
                BoardCard.needs_support.is_(True),
                ~_has_ref(BoardCard.owner_id, func.concat("sales:", BoardCard.id)),
            )
            .limit(limit)
        )
    )
    written = sum(
        raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.FROM_SALES,
            ref=f"sales:{card_id}",
            now=now,
            detail="Sotuv menejeri: mijoz yordam so'radi va to'ladi.",
        )
        for card_id, owner_id in rows
    )
    db.commit()
    return written


def meta_errors(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A launch Meta refused or that was rolled back, and a press of the
    client's own that Meta refused. The system's own retries are not
    here, nor refusals that are not Meta's (already paused, and the like)."""
    since = _since(db)
    if since is None:
        return 0
    finished = func.coalesce(CampaignLaunch.finished_at, CampaignLaunch.updated_at)
    launches = list(
        db.execute(
            select(
                CampaignLaunch.id, CampaignLaunch.owner_id, CampaignLaunch.error_message
            )
            .where(
                CampaignLaunch.status.in_(
                    [str(LaunchStatus.FAILED), str(LaunchStatus.ROLLED_BACK)]
                ),
                finished >= since,
                ~_has_ref(
                    CampaignLaunch.owner_id, func.concat("launch:", CampaignLaunch.id)
                ),
            )
            .order_by(finished)
            .limit(limit)
        )
    )
    presses = list(
        db.execute(
            select(
                ActionLog.id,
                ActionLog.owner_id,
                ActionLog.action,
                ActionLog.error_message,
            )
            .where(
                ActionLog.status == str(ActionStatus.FAILED),
                ActionLog.actor_type == str(ActorType.USER),
                ActionLog.created_at >= since,
                ActionLog.error_code.not_in(NOT_META_ERRORS),
                ~_has_ref(ActionLog.owner_id, func.concat("action:", ActionLog.id)),
            )
            .order_by(ActionLog.created_at)
            .limit(limit)
        )
    )
    written = 0
    for launch_id, owner_id, message in launches:
        written += raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.META_ERROR,
            ref=f"launch:{launch_id}",
            now=now,
            detail=_said("Reklama ishga tushmadi", message),
        )
    for action_id, owner_id, action, message in presses:
        written += raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.META_ERROR,
            ref=f"action:{action_id}",
            now=now,
            detail=_said(f"Amal bajarilmadi ({action})", message),
        )
    db.commit()
    return written


def _said(head: str, message: str | None) -> str:
    text = " ".join((message or "").split())[:300]
    return f"{head}: {text}" if text else head


def _has_ref(owner: Any, ref: Any) -> Any:
    """The client's ticket already holds this fact."""
    return exists().where(
        BoardCardEvent.owner_id == owner,
        BoardCardEvent.ref == ref,
        BoardCardEvent.card_id.in_(
            select(BoardCard.id).where(
                BoardCard.board == str(Board.SUPPORT), BoardCard.owner_id == owner
            )
        ),
    )


def sweep_support(db: Session, *, now: datetime) -> int:
    ensure_board(db, board=Board.SUPPORT, now=now)
    db.commit()
    return setup_late(db, now=now) + from_sales(db, now=now) + meta_errors(db, now=now)
