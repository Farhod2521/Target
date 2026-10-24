import uuid
from collections.abc import Collection
from datetime import datetime
from typing import Any

from paykit import ExternalId, InvoiceNumber, MinorUnits, TransactionRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.billing.constants import (
    PAYABLE_INVOICE_STATUSES,
    InvoiceKind,
    InvoiceStatus,
    SubscriptionStatus,
    TransactionState,
)
from app.modules.billing.models import (
    Invoice,
    PaymentTransaction,
    Plan,
    PromoRedemption,
    Subscription,
    SubscriptionChange,
)


def invoice_by_number(db: Session, *, number: str) -> Invoice | None:
    return db.scalar(select(Invoice).where(Invoice.number == number))


def payable_invoice(
    db: Session, *, owner: User, plan: Plan, now: datetime
) -> Invoice | None:
    return db.scalar(
        select(Invoice)
        .where(
            Invoice.owner_id == owner.id,
            Invoice.plan_id == plan.id,
            Invoice.kind == InvoiceKind.PLAN,
            Invoice.status.in_(PAYABLE_INVOICE_STATUSES),
            Invoice.expires_at > now,
        )
        .order_by(Invoice.created_at.desc())
        .limit(1)
    )


def open_page_bill(db: Session, *, owner: User, now: datetime) -> Invoice | None:
    return db.scalar(
        select(Invoice)
        .where(
            Invoice.owner_id == owner.id,
            Invoice.kind == InvoiceKind.PAGES,
            Invoice.status.in_(PAYABLE_INVOICE_STATUSES),
            Invoice.expires_at > now,
        )
        .order_by(Invoice.created_at.desc())
        .limit(1)
    )


def invoice_for(db: Session, *, owner: User, number: str) -> Invoice | None:
    return db.scalar(
        select(Invoice).where(Invoice.owner_id == owner.id, Invoice.number == number)
    )


def invoice_history(db: Session, *, owner: User) -> list[Invoice]:
    return list(
        db.scalars(
            select(Invoice)
            .where(Invoice.owner_id == owner.id)
            .order_by(Invoice.created_at.desc())
        )
    )


def open_invoices(db: Session, *, now: datetime) -> list[Invoice]:
    return list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.status.in_(PAYABLE_INVOICE_STATUSES), Invoice.expires_at <= now
            )
            .order_by(Invoice.expires_at)
        )
    )


def paid_invoice_count(db: Session, *, owner: User) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.owner_id == owner.id, Invoice.status == InvoiceStatus.PAID)
        )
        or 0
    )


def paid_before(db: Session, *, invoice: Invoice) -> bool:
    return (
        db.scalar(
            select(Invoice.id)
            .where(
                Invoice.owner_id == invoice.owner_id,
                Invoice.status.in_((InvoiceStatus.PAID, InvoiceStatus.REFUNDED)),
                Invoice.id != invoice.id,
            )
            .limit(1)
        )
        is not None
    )


def open_wallet_minor(db: Session, *, owner: User, currency: str) -> int:
    return int(
        db.scalar(
            select(func.sum(Invoice.wallet_minor)).where(
                Invoice.owner_id == owner.id,
                Invoice.status == InvoiceStatus.PENDING,
                Invoice.currency == currency,
            )
        )
        or 0
    )


def locked_invoice(db: Session, *, number: str) -> Invoice | None:
    return db.scalar(
        select(Invoice).where(Invoice.number == number).with_for_update(of=Invoice)
    )


def recent_invoices(
    db: Session, *, owner: User, limit: int
) -> list[tuple[Invoice, str]]:
    settled_by = (
        select(PaymentTransaction.provider)
        .where(
            PaymentTransaction.owner_id == owner.id,
            PaymentTransaction.invoice_id == Invoice.id,
            PaymentTransaction.state.in_(
                (TransactionState.PERFORMED, TransactionState.REFUNDED)
            ),
        )
        .limit(1)
        .scalar_subquery()
    )
    return [
        (invoice, paid_via or "")
        for invoice, paid_via in db.execute(
            select(Invoice, settled_by)
            .where(Invoice.owner_id == owner.id)
            .order_by(Invoice.created_at.desc())
            .limit(limit)
        )
    ]


def first_payments(
    db: Session, *, owner_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, Invoice]:
    if not owner_ids:
        return {}
    found: dict[uuid.UUID, Invoice] = {}
    for row in db.scalars(
        select(Invoice)
        .where(
            Invoice.owner_id.in_(list(owner_ids)),
            Invoice.status == InvoiceStatus.PAID,
            Invoice.kind == InvoiceKind.PLAN,
        )
        .order_by(Invoice.owner_id, Invoice.paid_at)
    ):
        if row.owner_id is not None:
            found.setdefault(row.owner_id, row)
    return found


def on_trial(
    db: Session, *, owner_ids: Collection[uuid.UUID], now: datetime
) -> set[uuid.UUID]:
    if not owner_ids:
        return set()
    return set(
        db.scalars(
            select(Subscription.owner_id).where(
                Subscription.owner_id.in_(list(owner_ids)),
                Subscription.status == SubscriptionStatus.TRIAL,
                Subscription.expires_at > now,
            )
        )
    )


def paid_count(db: Session, *, owner_ids: Collection[uuid.UUID]) -> int:
    if not owner_ids:
        return 0
    return int(
        db.scalar(
            select(func.count(func.distinct(Invoice.owner_id))).where(
                Invoice.owner_id.in_(list(owner_ids)),
                Invoice.status == InvoiceStatus.PAID,
                Invoice.kind == InvoiceKind.PLAN,
            )
        )
        or 0
    )


def orphaned_receipts(db: Session, *, email: str) -> list[Invoice]:
    address = email.strip()
    if not address:
        return []
    return list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.owner_id.is_(None),
                func.lower(Invoice.former_email) == address.lower(),
            )
            .order_by(Invoice.paid_at.desc())
        )
    )


def transaction_by_external(
    db: Session, *, provider: str, external_id: str
) -> PaymentTransaction | None:
    return db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.provider == provider,
            PaymentTransaction.external_id == external_id,
        )
    )


def transactions_in_window(
    db: Session, *, provider: str, start: datetime, end: datetime
) -> list[PaymentTransaction]:
    began = func.coalesce(
        PaymentTransaction.requested_at, PaymentTransaction.created_at
    )
    return list(
        db.scalars(
            select(PaymentTransaction)
            .where(
                PaymentTransaction.provider == provider, began >= start, began <= end
            )
            .order_by(began)
        )
    )


def held_transactions(db: Session, *, cutoff: datetime) -> list[PaymentTransaction]:
    return list(
        db.scalars(
            select(PaymentTransaction)
            .where(
                PaymentTransaction.state == TransactionState.CREATED,
                PaymentTransaction.created_at <= cutoff,
            )
            .order_by(PaymentTransaction.created_at)
        )
    )


def record_of(transaction: PaymentTransaction) -> TransactionRecord:
    return TransactionRecord(
        number=InvoiceNumber(transaction.invoice.number),
        reference=transaction.reference,
        external_id=ExternalId(transaction.external_id),
        state=transaction.state,  # type: ignore[arg-type]
        amount_minor=MinorUnits(transaction.amount_minor),
        created_at=transaction.created_at,
        requested_at=transaction.requested_at,
        performed_at=transaction.performed_at,
        canceled_at=transaction.canceled_at,
        cancel_reason=transaction.cancel_reason,
    )


def locked_attempt(
    db: Session, *, provider: str, external_id: str
) -> PaymentTransaction | None:
    found = transaction_by_external(db, provider=provider, external_id=external_id)
    if found is None:
        return None
    locked_invoice(db, number=found.invoice.number)
    db.refresh(found)
    return found


def subscription_history(db: Session, *, owner: User) -> list[dict[str, Any]]:
    rows = []
    for change in db.scalars(
        select(SubscriptionChange)
        .where(SubscriptionChange.owner_id == owner.id)
        .order_by(
            SubscriptionChange.occurred_at.desc(), SubscriptionChange.created_at.desc()
        )
    ):
        invoice = change.invoice
        discount = 0
        if invoice is not None:
            discount = int(
                db.scalar(
                    select(PromoRedemption.discount_minor)
                    .where(PromoRedemption.invoice_id == invoice.id)
                    .limit(1)
                )
                or 0
            )
        paid = invoice.amount_minor if invoice else 0
        credit = invoice.credit_minor if invoice else 0
        wallet = invoice.wallet_minor if invoice else 0
        rows.append(
            {
                "change": change,
                "paid_minor": paid,
                "credit_minor": credit,
                "wallet_minor": wallet,
                "discount_minor": discount,
                "price_minor": paid + credit + wallet + discount,
            }
        )
    return rows
