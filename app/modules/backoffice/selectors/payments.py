"""Bills and entitlements across every account, for the Owner and super admin.

Two currencies never add, so every sum here is a list per currency.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

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
from app.modules.businesses.models import Business

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
    earned_count: int
    earned_before: Money
    unpaid: int
    unpaid_sums: Money
    stuck: int
    stuck_sums: Money
    refunded: int
    refunded_sums: Money


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
    counts: dict[str, int]

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
    counts: dict[str, int]

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
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    is_open = Invoice.status.in_(OPEN_STATUSES)
    is_paid = Invoice.status == InvoiceStatus.PAID
    refunded = (
        Invoice.status == InvoiceStatus.REFUNDED,
        Invoice.updated_at >= month_start,
    )
    stuck = db.execute(
        select(PaymentTransaction.currency, func.sum(PaymentTransaction.amount_minor))
        .where(*_stuck_where(now=now))
        .group_by(PaymentTransaction.currency)
        .order_by(PaymentTransaction.currency)
    ).all()
    return Totals(
        earned=_sums(db, is_paid, Invoice.paid_at >= month_start),
        earned_count=_count(db, is_paid, Invoice.paid_at >= month_start),
        earned_before=_sums(
            db,
            is_paid,
            Invoice.paid_at >= last_month_start,
            Invoice.paid_at < month_start,
        ),
        unpaid=_count(db, is_open),
        unpaid_sums=_sums(db, is_open),
        stuck=int(
            db.scalar(select(func.count()).select_from(_stuck(now=now).subquery())) or 0
        ),
        stuck_sums=tuple((currency, int(total)) for currency, total in stuck),
        refunded=_count(db, *refunded),
        refunded_sums=_sums(db, *refunded),
    )


def _stuck_where(*, now: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        PaymentTransaction.state == TransactionState.CREATED,
        PaymentTransaction.created_at <= now - timedelta(hours=STUCK_HOLD_HOURS),
    )


def _stuck(*, now: datetime) -> Select[Any]:
    return select(PaymentTransaction).where(*_stuck_where(now=now))


def stuck_holds(db: Session, *, now: datetime) -> list[PaymentTransaction]:
    """Attempts still holding a bill nobody can pay, oldest first."""
    return list(
        db.scalars(
            _stuck(now=now)
            .options(
                joinedload(PaymentTransaction.owner),
                joinedload(PaymentTransaction.invoice).joinedload(Invoice.plan),
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


def by_owner(term: str) -> list[ColumnElement[bool]]:
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
        Invoice.number.ilike(like), Invoice.former_email.ilike(like), *by_owner(term)
    )


def _subscription_term(term: str) -> ColumnElement[bool]:
    return or_(*by_owner(term)) if term else true()


def _invoice_counts(db: Session, *, term: str) -> dict[str, int]:
    """Each chip's bills inside the search. `all` also holds what no chip names."""
    rows = db.execute(
        select(Invoice.status, func.count(Invoice.id))
        .outerjoin(User, Invoice.owner_id == User.id)
        .where(_invoice_term(term))
        .group_by(Invoice.status)
    ).all()
    by_status = {str(status): int(count) for status, count in rows}

    def sum_of(*statuses: InvoiceStatus) -> int:
        return sum(by_status.get(str(status), 0) for status in statuses)

    return {
        "all": sum(by_status.values()),
        "open": sum_of(*OPEN_STATUSES),
        "paid": sum_of(InvoiceStatus.PAID),
        "closed": sum_of(*CLOSED_STATUSES),
    }


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
        counts=_invoice_counts(db, term=term),
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
    every = _live(now=now).where(_subscription_term(term))
    settled = exists().where(
        Invoice.owner_id == Subscription.owner_id,
        Invoice.status == InvoiceStatus.PAID,
    )
    unpaid = every.where(Plan.price > 0, ~settled)
    counts = {
        "all": _rows_in(db, every),
        UNPAID: _rows_in(db, unpaid),
    }
    query = unpaid if state == UNPAID else every
    rows = db.scalars(
        query.order_by(Subscription.expires_at, Subscription.id)
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    return SubscriptionPage(
        rows=tuple(rows), total=counts[state or "all"], offset=offset, counts=counts
    )


def _rows_in(db: Session, query: Select[Any]) -> int:
    return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)


def settled_owners(db: Session, owners: Iterable[UUID]) -> frozenset[UUID]:
    """Which of these accounts ever had a bill settled."""
    return frozenset(
        db.scalars(
            select(Invoice.owner_id)
            .where(
                Invoice.owner_id.in_(set(owners)),
                Invoice.status == InvoiceStatus.PAID,
            )
            .distinct()
        )
    )


def business_names(db: Session, owners: Iterable[UUID]) -> dict[UUID, str]:
    """The first profile each account made, for a list's customer line."""
    names: dict[UUID, str] = {}
    rows = db.execute(
        select(Business.user_id, Business.name)
        .where(Business.user_id.in_(set(owners)))
        .order_by(Business.created_at)
    )
    for owner_id, name in rows:
        names.setdefault(owner_id, name)
    return names
