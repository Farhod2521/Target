"""Take a payment entered in testing out of the database, by hand.

Run only from ``tools/erase_payment.py``; no office screen reaches this. The
bill goes with every attempt on it and whatever it paid out, so a test payment
leaves neither takings nor a balance behind. The subscription keeps its days:
one bill's share of them cannot be told from the rest.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.orm import Session

from app.common.deletion import delete_rows
from app.modules.billing.models import (
    Invoice,
    PaymentTransaction,
    PromoRedemption,
    SubscriptionChange,
)
from app.modules.referrals.models import ReferralReward, WalletSpend
from app.modules.sales.models import SalesCommission


@dataclass(frozen=True, slots=True)
class ErasedPayment:
    number: str
    status: str
    email: str
    amount_minor: int
    currency: str
    attempts: int
    rewards: int
    commissions: int
    wallet_spends: int
    changes_unlinked: int
    promos_unlinked: int


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def invoices_for(db: Session, *, key: str) -> list[Invoice]:
    """The bills a transaction id, a provider's id, a reference or an invoice
    number names. More than one means a provider's id two providers share."""
    matches: list[ColumnElement[bool]] = [
        PaymentTransaction.external_id == key,
        PaymentTransaction.reference == key,
    ]
    numbered: list[ColumnElement[bool]] = [Invoice.number == key]
    identifier = _as_uuid(key)
    if identifier is not None:
        matches.append(PaymentTransaction.id == identifier)
        numbered.append(Invoice.id == identifier)
    attempted = select(PaymentTransaction.invoice_id).where(or_(*matches))
    return list(
        db.scalars(
            select(Invoice)
            .where(or_(Invoice.id.in_(attempted), *numbered))
            .order_by(Invoice.created_at)
            .with_for_update()
        )
    )


def erase_payment(db: Session, *, invoice: Invoice) -> ErasedPayment:
    """Delete one bill and what hangs off it. The caller commits or rolls back."""
    invoice_id = invoice.id
    email = invoice.owner.email if invoice.owner else invoice.former_email
    erased = ErasedPayment(
        number=invoice.number,
        status=invoice.status,
        email=email,
        amount_minor=invoice.amount_minor,
        currency=invoice.currency,
        attempts=delete_rows(
            db,
            PaymentTransaction.__table__,
            PaymentTransaction.__table__.c.invoice_id == invoice_id,
        ),
        rewards=delete_rows(
            db,
            ReferralReward.__table__,
            ReferralReward.__table__.c.invoice_id == invoice_id,
        ),
        commissions=delete_rows(
            db,
            SalesCommission.__table__,
            SalesCommission.__table__.c.invoice_id == invoice_id,
        ),
        wallet_spends=delete_rows(
            db, WalletSpend.__table__, WalletSpend.__table__.c.invoice_id == invoice_id
        ),
        changes_unlinked=db.execute(
            update(SubscriptionChange)
            .where(SubscriptionChange.invoice_id == invoice_id)
            .values(invoice_id=None)
        ).rowcount,
        promos_unlinked=db.execute(
            update(PromoRedemption)
            .where(PromoRedemption.invoice_id == invoice_id)
            .values(invoice_id=None)
        ).rowcount,
    )
    db.expunge(invoice)
    delete_rows(db, Invoice.__table__, Invoice.__table__.c.id == invoice_id)
    return erased
