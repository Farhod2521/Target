"""Answering, recording and voiding Hamyon payouts from the office.

The money decision is referrals'; what this adds is the journal line - who
paid, refused, recorded or voided it, and the sentence they gave.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.money import to_minor
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.services.journal import record
from app.modules.referrals.constants import PayoutMethod
from app.modules.referrals.models import WithdrawalRequest
from app.modules.referrals.selectors import wallet_balance
from app.modules.referrals.services import (
    pay_withdrawal,
    record_payout,
    reject_withdrawal,
    void_payout,
)


def payout_currencies(db: Session, *, customer: User) -> tuple[str, ...]:
    """Currencies this Hamyon ever moved, the billing currency first."""
    held = [row.currency for row in wallet_balance(db, owner=customer)]
    if settings.billing_currency in held:
        held.remove(settings.billing_currency)
        return (settings.billing_currency, *held)
    if held:
        return tuple(held)
    return (settings.billing_currency,)


def record_withdrawal(
    db: Session,
    *,
    customer: User,
    amount: Decimal,
    currency: str,
    method: PayoutMethod,
    pay_reference: str,
    actor: User,
    reason: str,
    now: datetime,
) -> WithdrawalRequest:
    """Record that this Hamyon paid out, after the money already moved."""
    payout = record_payout(
        db,
        owner=customer,
        amount_minor=int(to_minor(amount=amount, currency=currency)),
        currency=currency,
        method=method,
        pay_reference=pay_reference,
        actor=actor,
        reason=reason,
        now=now,
    )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.WITHDRAWAL_PAID,
        reason=reason,
        detail={
            "amount_minor": payout.amount_minor,
            "currency": payout.currency,
            "method": str(method),
            "pay_reference": payout.pay_reference,
        },
    )
    return payout


def pay_ask(
    db: Session,
    *,
    ask: WithdrawalRequest,
    pay_reference: str,
    actor: User,
    now: datetime,
) -> WithdrawalRequest:
    """Mark an earner's ask paid; no reason owed, the reference is the trail."""
    paid = pay_withdrawal(
        db, ask=ask, pay_reference=pay_reference, actor=actor, now=now
    )
    record(
        db,
        customer=paid.owner,
        actor=actor,
        kind=ActionKind.WITHDRAWAL_PAID,
        detail={
            "amount_minor": paid.amount_minor,
            "currency": paid.currency,
            "method": str(paid.method),
            "pay_reference": paid.pay_reference,
            "card_last4": paid.card_last4,
        },
    )
    return paid


def refuse_ask(
    db: Session, *, ask: WithdrawalRequest, reason: str, actor: User, now: datetime
) -> WithdrawalRequest:
    """Turn an earner's ask down, keeping the sentence they will read."""
    refused = reject_withdrawal(db, ask=ask, reason=reason, actor=actor, now=now)
    record(
        db,
        customer=refused.owner,
        actor=actor,
        kind=ActionKind.WITHDRAWAL_REJECTED,
        reason=reason,
        detail={"amount_minor": refused.amount_minor, "currency": refused.currency},
    )
    return refused


def void_withdrawal(
    db: Session, *, payout: WithdrawalRequest, actor: User, reason: str, now: datetime
) -> WithdrawalRequest:
    """Void a mistaken payout record; the row stays, the balance follows back up."""
    voided = void_payout(db, payout=payout, actor=actor, reason=reason, now=now)
    record(
        db,
        customer=voided.owner,
        actor=actor,
        kind=ActionKind.WITHDRAWAL_VOIDED,
        reason=reason,
        detail={"amount_minor": voided.amount_minor, "currency": voided.currency},
    )
    return voided
