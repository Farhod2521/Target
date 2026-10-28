"""What the office hands over from a customer's card, and the money with it.

Each is billing's or referrals' write plus one journal row saying who did it
and why. When the customer paid, the grant goes through ``record_payment``,
which writes a paid bill and lands the access the way a provider's payment
does; when nobody paid it leaves no bill. Nothing here validates: the ranges
and the required sentence are billing's.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.common.exceptions import ConfigurationError
from app.common.money import to_minor
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.services.journal import record
from app.modules.billing.constants import ManualMethod
from app.modules.billing.exceptions import NothingToExtend
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors import latest_subscription
from app.modules.billing.services import (
    grant_days,
    grant_pages,
    grant_plan,
    record_payment,
    revoke_pages,
)
from app.modules.referrals.constants import ReferralMode
from app.modules.referrals.services import set_referral_access


@dataclass(frozen=True, slots=True)
class Payment:
    """Money that came with a grant, in whole units as written on a receipt."""

    amount: Decimal
    method: ManualMethod
    reference: str


def give_plan(
    db: Session,
    *,
    customer: User,
    plan: Plan,
    payment: Payment | None,
    actor: User,
    reason: str,
    now: datetime,
) -> Subscription:
    """Put this account on ``plan`` with the plan's whole period."""
    invoice = None
    if payment is not None:
        invoice = pay(
            db,
            customer=customer,
            plan=plan,
            days=plan.period_days,
            payment=payment,
            actor=actor,
            reason=reason,
            now=now,
        )
        subscription = _bought(db, invoice)
    else:
        subscription = grant_plan(
            db, owner=customer, plan=plan, actor=actor, reason=reason, now=now
        )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.PLAN_GIVEN,
        reason=reason,
        detail={
            "plan": plan.code,
            "days": plan.period_days,
            "until": subscription.expires_at.isoformat(),
            **money(invoice),
        },
    )
    return subscription


def add_days(
    db: Session,
    *,
    customer: User,
    days: int,
    payment: Payment | None,
    actor: User,
    reason: str,
    now: datetime,
) -> Subscription:
    """Extend the entitlement; paid days are sold on the current or last plan."""
    invoice = None
    if payment is not None:
        invoice = pay(
            db,
            customer=customer,
            plan=_current_plan(db, customer=customer),
            days=days,
            payment=payment,
            actor=actor,
            reason=reason,
            now=now,
        )
        subscription = _bought(db, invoice)
    else:
        subscription = grant_days(
            db, owner=customer, days=days, actor=actor, reason=reason, now=now
        )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.DAYS_GRANTED,
        reason=reason,
        detail={
            "days": days,
            "until": subscription.expires_at.isoformat(),
            **money(invoice),
        },
    )
    return subscription


def add_slots(
    db: Session,
    *,
    customer: User,
    pages: int,
    payment: Payment | None,
    actor: User,
    reason: str,
    now: datetime,
) -> Subscription:
    """Room for more pages; a paid one leaves a bill that moves no date."""
    subscription = grant_pages(
        db, owner=customer, pages=pages, actor=actor, reason=reason, now=now
    )
    invoice = None
    if payment is not None:
        invoice = pay(
            db,
            customer=customer,
            plan=subscription.plan,
            days=0,
            payment=payment,
            actor=actor,
            reason=reason,
            now=now,
        )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.PAGES_GRANTED,
        reason=reason,
        detail={"pages": pages, "extra": subscription.extra_pages, **money(invoice)},
    )
    return subscription


def take_slots(
    db: Session,
    *,
    customer: User,
    pages: int,
    actor: User,
    reason: str,
    now: datetime,
) -> Subscription:
    """Take room back; pages already switched on keep running."""
    subscription = revoke_pages(
        db, owner=customer, pages=pages, actor=actor, reason=reason, now=now
    )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.PAGES_REVOKED,
        reason=reason,
        detail={"pages": pages, "extra": subscription.extra_pages},
    )
    return subscription


def take_payment(
    db: Session,
    *,
    customer: User,
    payment: Payment,
    actor: User,
    reason: str,
    now: datetime,
) -> Invoice:
    """Write down money for access the account already has; no date moves."""
    invoice = pay(
        db,
        customer=customer,
        plan=_current_plan(db, customer=customer),
        days=0,
        payment=payment,
        actor=actor,
        reason=reason,
        now=now,
    )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.PAYMENT_RECORDED,
        reason=reason,
        detail=money(invoice),
    )
    return invoice


def set_referral(
    db: Session,
    *,
    customer: User,
    mode: ReferralMode,
    actor: User,
    reason: str,
    now: datetime,
) -> None:
    """Open, close, or hand back to the rule this account's invitation link."""
    set_referral_access(
        db, owner=customer, mode=mode, actor=actor, reason=reason, now=now
    )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.REFERRAL_CHANGED,
        reason=reason,
        detail={"mode": str(mode)},
    )


def pay(
    db: Session,
    *,
    customer: User,
    plan: Plan,
    days: int,
    payment: Payment,
    actor: User,
    reason: str,
    now: datetime,
) -> Invoice:
    return record_payment(
        db,
        owner=customer,
        plan=plan,
        amount_minor=int(to_minor(amount=payment.amount, currency=plan.currency)),
        days=days,
        method=payment.method,
        reference=payment.reference,
        actor=actor,
        reason=reason,
        now=now,
    )


def _bought(db: Session, invoice: Invoice) -> Subscription:
    """The entitlement a paid bill landed on - ``apply_payment`` always sets it."""
    subscription = (
        db.get(Subscription, invoice.subscription_id)
        if invoice.subscription_id
        else None
    )
    if subscription is None:
        raise ConfigurationError("a paid bill landed on no subscription")
    return subscription


def _current_plan(db: Session, *, customer: User) -> Plan:
    subscription = latest_subscription(db, owner=customer)
    if subscription is None:
        raise NothingToExtend
    plan: Plan = subscription.plan
    return plan


def money(invoice: Invoice | None) -> dict[str, Any]:
    """The journal's half of a paid grant: which bill, and what came in."""
    if invoice is None:
        return {}
    return {
        "invoice": invoice.number,
        "amount_minor": invoice.amount_minor,
        "credit_minor": invoice.credit_minor,
        "currency": invoice.currency,
        "method": invoice.manual_method,
    }
