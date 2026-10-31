"""Bills and entitlements across every account, for the Owner and super admin.

Two currencies never add, so every sum here is a list per currency.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, func, or_, select, true
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.backoffice.constants import (
    EXPIRING_DAYS,
    PAGE_SIZE,
    STUCK_HOLD_HOURS,
)
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceStatus,
    TransactionState,
)
from app.modules.billing.models import (
    Invoice,
    PaymentTransaction,
    Plan,
    Subscription,
)

OPEN_STATUSES = (InvoiceStatus.PENDING, InvoiceStatus.HELD)
CLOSED_STATUSES = (InvoiceStatus.CANCELED, InvoiceStatus.EXPIRED)
UNPAID = "unpaid"

INVOICE_STATES: tuple[tuple[str, str], ...] = (
    ("", "Hammasi"),
    ("open", "To'lanmagan"),
    ("paid", "To'langan"),
    ("closed", "Yopilgan"),
)
SUBSCRIPTION_STATES: tuple[tuple[str, str], ...] = (
    ("", "Hammasi"),
    (UNPAID, "To'lovsiz"),
)

Money = tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class Totals:
    earned: Money
    unpaid: int
    unpaid_sums: Money
    stuck: int
    refunded: int


@dataclass(frozen=True, slots=True)
class InvoiceRow:
    """A bill and the last attempt to pay it; a bill written by hand has none."""

    invoice: Invoice
    attempt: PaymentTransaction | None


@dataclass(frozen=True, slots=True)
class InvoicePage:
    rows: tuple[InvoiceRow, ...]
    total: int
    offset: int

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.rows)

    @property
    def has_more(self) -> bool:
        return self.next_offset < self.total


@dataclass(frozen=True, slots=True)
class SubscriptionPage:
    rows: tuple[Subscription, ...]
    total: int
    offset: int

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.rows)

    @property
    def has_more(self) -> bool:
        return self.next_offset < self.total


def _sums(db: Session, *where: ColumnElement[bool]) -> Money:
    rows = db.execute(
        select(Invoice.currency, func.sum(Invoice.amount_minor))
        .where(*where)
        .group_by(Invoice.currency)
        .order_by(Invoice.currency)
    ).all()
    return tuple((currency, int(total)) for currency, total in rows)


def _count(db: Session, *where: ColumnElement[bool]) -> int:
    return int(db.scalar(select(func.count(Invoice.id)).where(*where)) or 0)


def totals(db: Session, *, now: datetime) -> Totals:
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    is_open = Invoice.status.in_(OPEN_STATUSES)
    return Totals(
        earned=_sums(
            db, Invoice.status == InvoiceStatus.PAID, Invoice.paid_at >= month_start
        ),
        unpaid=_count(db, is_open),
        unpaid_sums=_sums(db, is_open),
        stuck=int(
            db.scalar(select(func.count()).select_from(_stuck(now=now).subquery())) or 0
        ),
        refunded=_count(
            db,
            Invoice.status == InvoiceStatus.REFUNDED,
            Invoice.updated_at >= month_start,
        ),
    )


def _stuck(*, now: datetime) -> Select[Any]:
    return select(PaymentTransaction).where(
        PaymentTransaction.state == TransactionState.CREATED,
        PaymentTransaction.created_at <= now - timedelta(hours=STUCK_HOLD_HOURS),
    )


def stuck_holds(db: Session, *, now: datetime) -> list[PaymentTransaction]:
    """Attempts still holding a bill nobody can pay, oldest first."""
    return list(
        db.scalars(
            _stuck(now=now)
            .options(
                joinedload(PaymentTransaction.owner),
                joinedload(PaymentTransaction.invoice),
            )
            .order_by(PaymentTransaction.created_at)
        )
    )


def _by_state(state: str) -> ColumnElement[bool]:
    if state == "open":
        return Invoice.status.in_(OPEN_STATUSES)
    if state == "paid":
        return Invoice.status == InvoiceStatus.PAID
    if state == "closed":
        return Invoice.status.in_(CLOSED_STATUSES)
    return true()


def _by_owner(term: str) -> list[ColumnElement[bool]]:
    """Whoever the caller named: an address, a name, a telephone number."""
    like = f"%{term}%"
    digits = re.sub(r"[\s()-]", "", term) or term
    return [
        User.email.ilike(like),
        User.full_name.ilike(like),
        User.phone.ilike(f"%{digits}%"),
    ]


def _invoice_term(term: str) -> ColumnElement[bool]:
    if not term:
        return true()
    like = f"%{term}%"
    return or_(
        Invoice.number.ilike(like), Invoice.former_email.ilike(like), *_by_owner(term)
    )


def _subscription_term(term: str) -> ColumnElement[bool]:
    return or_(*_by_owner(term)) if term else true()


def _last_attempts(
    db: Session, invoices: list[Invoice]
) -> dict[Any, PaymentTransaction]:
    attempts = db.scalars(
        select(PaymentTransaction)
        .where(PaymentTransaction.invoice_id.in_([row.id for row in invoices]))
        .order_by(PaymentTransaction.created_at)
    )
    return {attempt.invoice_id: attempt for attempt in attempts}


def invoice_page(
    db: Session, *, state: str = "", term: str = "", offset: int = 0
) -> InvoicePage:
    """One screenful of bills, newest first. A deleted account's receipt has
    no owner and stays on the list, so the join is an outer one."""
    where = (_by_state(state), _invoice_term(term))
    total = db.scalar(
        select(func.count(Invoice.id))
        .outerjoin(User, Invoice.owner_id == User.id)
        .where(*where)
    )
    invoices = list(
        db.scalars(
            select(Invoice)
            .outerjoin(User, Invoice.owner_id == User.id)
            .options(
                joinedload(Invoice.owner),
                joinedload(Invoice.plan),
                joinedload(Invoice.recorded_by),
            )
            .where(*where)
            .order_by(Invoice.created_at.desc(), Invoice.id)
            .offset(offset)
            .limit(PAGE_SIZE)
        )
    )
    attempts = _last_attempts(db, invoices) if invoices else {}
    return InvoicePage(
        rows=tuple(InvoiceRow(row, attempts.get(row.id)) for row in invoices),
        total=int(total or 0),
        offset=offset,
    )


def _live(*, now: datetime) -> Select[Any]:
    """Live by its end date as well as its status: a subscription whose time
    ran out keeps saying ``active`` until something else moves it."""
    return (
        select(Subscription)
        .join(User, Subscription.owner_id == User.id)
        .join(Plan, Subscription.plan_id == Plan.id)
        .options(joinedload(Subscription.owner), joinedload(Subscription.plan))
        .where(
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > now,
        )
    )


def running_out(db: Session, *, now: datetime) -> list[Subscription]:
    """Entitlements ending inside the warning window, soonest first."""
    return list(
        db.scalars(
            _live(now=now)
            .where(Subscription.expires_at < now + timedelta(days=EXPIRING_DAYS))
            .order_by(Subscription.expires_at)
        )
    )


def subscription_page(
    db: Session, *, now: datetime, state: str = "", term: str = "", offset: int = 0
) -> SubscriptionPage:
    """Live entitlements, soonest to end first. ``unpaid``: on a priced plan
    with no bill ever settled, so nobody wrote down whether they paid."""
    query = _live(now=now).where(_subscription_term(term))
    if state == UNPAID:
        settled = exists().where(
            Invoice.owner_id == Subscription.owner_id,
            Invoice.status == InvoiceStatus.PAID,
        )
        query = query.where(Plan.price > 0, ~settled)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Subscription.expires_at, Subscription.id)
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    return SubscriptionPage(rows=tuple(rows), total=int(total or 0), offset=offset)
