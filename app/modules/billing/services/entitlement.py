"""The building blocks every write in billing stands on: entitlement, history, bills."""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import on_commit
from app.common.exceptions import ConfigurationError
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.billing.constants import (
    DEFAULT_PLAN_CODE,
    INVOICE_NUMBER_DIGITS,
    LIVE_SUBSCRIPTION_STATUSES,
    NUMBER_ATTEMPTS,
    TRANSACTION_REFERENCE_DIGITS,
    HistoryKind,
    InvoiceStatus,
    PlanMove,
    PromoKind,
    SubscriptionStatus,
)
from app.modules.billing.exceptions import CheaperPlanWaits
from app.modules.billing.models import (
    Invoice,
    Plan,
    PromoCode,
    PromoRedemption,
    Subscription,
    SubscriptionChange,
)
from app.modules.billing.selectors import (
    bound_subscription,
    plan_move,
    plan_switch,
    prepared_account,
    running_page_bills,
)

logger = logging.getLogger(__name__)
TRIAL_PLAN_DEFAULTS: dict[str, Any] = {
    "name": "Start",
    "price": 0,
    "period_days": 30,
    "max_adsets": 10,
    "daily_chat_requests": 20,
    "llm_cost_limit_minor": 1_000,
    "is_active": True,
    "sort_order": 0,
}


def _digits(length: int) -> str:
    return secrets.choice("123456789") + "".join(
        secrets.choice("0123456789") for _ in range(length - 1)
    )


def new_invoice_number() -> str:
    return _digits(INVOICE_NUMBER_DIGITS)


def new_transaction_reference() -> str:
    return _digits(TRANSACTION_REFERENCE_DIGITS)


def payer(invoice: Invoice) -> User:
    if invoice.owner is None:
        raise ConfigurationError("a kept receipt has no account to act for")
    return invoice.owner


def default_plan(db: Session) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.code == DEFAULT_PLAN_CODE))
    if plan is None:
        plan = Plan(
            code=DEFAULT_PLAN_CODE,
            currency=settings.billing_currency,
            tagline="",
            features="",
            included_pages=1,
            included_google_accounts=0,
            extra_page_price=0,
            is_one_time=False,
            **TRIAL_PLAN_DEFAULTS,
        )
        db.add(plan)
        db.flush()
    return plan


def locked_entitlement(db: Session, *, owner: User) -> Subscription | None:
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        )
        .limit(1)
        .with_for_update()
    )


def latest_locked(db: Session, *, owner: User) -> Subscription | None:
    live = locked_entitlement(db, owner=owner)
    if live is not None:
        return live
    return db.scalar(
        select(Subscription)
        .where(Subscription.owner_id == owner.id)
        .order_by(Subscription.started_at.desc())
        .limit(1)
        .with_for_update()
    )


def open_entitlement(
    db: Session, *, owner: User, plan: Plan, days: int, now: datetime
) -> Subscription:
    previous = bound_subscription(db, owner=owner)
    if previous is None:
        account = prepared_account(db, owner=owner)
        subscription = Subscription(
            owner_id=owner.id,
            plan_id=plan.id,
            ad_account_id=account.id if account else None,
            setup_completed_at=owner.prepared_at,
            extra_pages=0,
        )
    else:
        subscription = Subscription(
            owner_id=owner.id,
            plan_id=plan.id,
            ad_account_id=previous.ad_account_id,
            setup_completed_at=previous.setup_completed_at,
            extra_pages=previous.extra_pages,
        )
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.started_at = now
    subscription.term_started_at = now
    subscription.expires_at = now + timedelta(days=days)
    subscription.note = ""
    db.add(subscription)
    db.flush()
    db.refresh(subscription)
    return subscription


def land_plan(
    db: Session, *, subscription: Subscription, plan: Plan, days: int, now: datetime
) -> PlanMove:
    move = plan_move(subscription=subscription, plan=plan, now=now)
    if move == PlanMove.STACK:
        if subscription.expires_at <= now:
            subscription.term_started_at = now
        subscription.expires_at = max(subscription.expires_at, now) + timedelta(
            days=days
        )
    else:
        if move == PlanMove.WAIT:
            logger.warning(
                "cheaper plan %s landed on a live %s for %s",
                plan.code,
                subscription.plan.code,
                subscription.owner_id,
            )
        subscription.term_started_at = now
        subscription.expires_at = now + timedelta(days=days)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.plan_id = plan.id
    subscription.plan = plan
    subscription.canceled_at = None
    subscription.ended_at = None
    db.flush()
    return move


def record_change(
    db: Session,
    *,
    subscription: Subscription,
    kind: HistoryKind,
    from_plan: Plan | None,
    move: PlanMove | None,
    days: int,
    expires_before: datetime | None,
    now: datetime,
    invoice: Invoice | None = None,
    actor: User | None = None,
    reason: str = "",
) -> SubscriptionChange:
    change = SubscriptionChange(
        owner_id=subscription.owner_id,
        subscription_id=subscription.id,
        kind=kind,
        move=move or "",
        from_plan_id=from_plan.id if from_plan else None,
        to_plan_id=subscription.plan_id,
        days=days,
        expires_before=expires_before,
        expires_after=subscription.expires_at,
        invoice_id=invoice.id if invoice else None,
        actor_id=actor.id if actor else None,
        reason=reason.strip(),
        occurred_at=now,
    )
    db.add(change)
    db.flush()
    return change


def insert_invoice(
    db: Session,
    *,
    owner: User,
    plan: Plan,
    amount_minor: int,
    period_days: int,
    expires_at: datetime,
    now: datetime,
    **fields: Any,
) -> Invoice:
    for _attempt in range(NUMBER_ATTEMPTS):
        invoice = Invoice(
            owner_id=owner.id,
            number=new_invoice_number(),
            plan_id=plan.id,
            amount_minor=amount_minor,
            currency=plan.currency,
            period_days=period_days,
            expires_at=expires_at,
            status=InvoiceStatus.PENDING,
            **fields,
        )
        try:
            with db.begin_nested():
                db.add(invoice)
        except IntegrityError:
            continue
        db.refresh(invoice)
        emit(
            db,
            owner_id=owner.id,
            name=EventName.INVOICE_CREATED,
            aggregate_type="invoice",
            aggregate_id=invoice.id,
            payload={
                "number": invoice.number,
                "plan": plan.code,
                "amount_minor": invoice.amount_minor,
                "currency": invoice.currency,
                "period_days": invoice.period_days,
            },
            occurred_at=now,
        )
        return invoice
    raise ConfigurationError("invoice number generator produced only collisions")


def lift_wallet(db: Session, *, owner: User, now: datetime) -> None:
    from app.modules.referrals.services import hold_wallet

    for bill in db.scalars(
        select(Invoice)
        .where(
            Invoice.owner_id == owner.id,
            Invoice.status == InvoiceStatus.PENDING,
            Invoice.wallet_minor > 0,
        )
        .with_for_update(of=Invoice)
    ):
        hold_wallet(db, invoice=bill, amount_minor=0, now=now)
        bill.amount_minor += bill.wallet_minor
        bill.wallet_minor = 0
    db.flush()


def release_discount(
    db: Session, *, redemption: PromoRedemption, invoice: Invoice, now: datetime
) -> None:
    invoice.amount_minor += redemption.discount_minor
    emit(
        db,
        owner_id=invoice.owner_id,
        name=EventName.PROMO_RELEASED,
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "number": invoice.number,
            "code": redemption.promo.code,
            "discount_minor": redemption.discount_minor,
            "amount_minor": invoice.amount_minor,
            "currency": invoice.currency,
        },
        occurred_at=now,
    )
    db.delete(redemption)
    db.flush()


def land_pages(db: Session, *, invoice: Invoice, now: datetime) -> Subscription:
    from app.modules.referrals.services import accrue_reward
    from app.modules.sales.services import credit_sale

    owner = payer(invoice)
    subscription = locked_entitlement(db, owner=owner) or bound_subscription(
        db, owner=owner
    )
    if subscription is None:
        raise ConfigurationError("page bill paid for an account with no subscription")
    if subscription.expires_at <= now:
        logger.warning("page bill %s paid after the period ended", invoice.number)
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = now
    invoice.subscription_id = subscription.id
    invoice.applied_days = 0
    invoice.pages_from = now
    invoice.pages_until = max(now, subscription.expires_at)
    db.flush()
    record_change(
        db,
        subscription=subscription,
        kind=HistoryKind.PAGES,
        from_plan=subscription.plan,
        move=None,
        days=0,
        expires_before=subscription.expires_at,
        now=now,
        invoice=invoice,
        actor=db.get(User, invoice.recorded_by_id) if invoice.recorded_by_id else None,
    )
    accrue_reward(db, invoice=invoice, now=now)
    credit_sale(db, invoice=invoice, now=now)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PAYMENT_RECEIVED,
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "number": invoice.number,
            "kind": invoice.kind,
            "plan": invoice.plan.code,
            "amount_minor": invoice.amount_minor,
            "wallet_minor": invoice.wallet_minor,
            "currency": invoice.currency,
            "pages": invoice.pages,
        },
        occurred_at=now,
    )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PAGES_ADDED,
        aggregate_type="subscription",
        aggregate_id=subscription.id,
        payload={
            "pages": invoice.pages,
            "until": invoice.pages_until.isoformat() if invoice.pages_until else None,
            "invoice": invoice.number,
        },
        occurred_at=now,
    )
    return subscription


def run_plan_pages(
    db: Session,
    *,
    invoice: Invoice,
    subscription: Subscription,
    move: PlanMove,
    before: datetime | None,
    now: datetime,
) -> None:
    was_running = before is not None and before > now
    if move == PlanMove.RESTART and was_running:
        ids = [
            bill.id
            for bill in running_page_bills(db, owner=payer(invoice), at=now)
            if bill.currency == invoice.currency and bill.id != invoice.id
        ]
        if ids:
            db.execute(
                update(Invoice).where(Invoice.id.in_(ids)).values(pages_until=now)
            )
    if invoice.pages <= 0:
        return
    stacked = move == PlanMove.STACK and was_running and before is not None
    invoice.pages_from = before if stacked else now
    invoice.pages_until = subscription.expires_at


def resume_lapsed(db: Session, *, owner_id: str) -> None:
    from app.modules.ads.tasks import resume_after_payment_task

    on_commit(db, lambda: resume_after_payment_task.delay(owner_id))


def opens_subscription(*, promo: PromoCode) -> bool:
    return promo.kind == PromoKind.PLAN and bool(promo.grant_days)


def open_promo_entitlement(
    db: Session, *, owner: User, promo: PromoCode, now: datetime
) -> Subscription:
    account = prepared_account(db, owner=owner)
    plan = promo.plan or default_plan(db)
    subscription = Subscription(
        owner_id=owner.id,
        plan_id=plan.id,
        ad_account_id=account.id if account else None,
        setup_completed_at=owner.prepared_at,
        status=SubscriptionStatus.ACTIVE,
        extra_pages=0,
        started_at=now,
        expires_at=now,
        note="",
    )
    db.add(subscription)
    db.flush()
    db.refresh(subscription)
    return subscription


def require_grantable(
    db: Session, *, subscription: Subscription | None, promo: PromoCode, now: datetime
) -> None:
    if subscription is None or promo.plan is None:
        return
    owner = db.get(User, subscription.owner_id)
    assert owner is not None
    until = plan_switch(db, owner=owner, plan=promo.plan, now=now).until
    if until is not None:
        raise CheaperPlanWaits(until=until)


def apply_grant(
    db: Session,
    *,
    subscription: Subscription,
    promo: PromoCode,
    from_plan: Plan | None,
    actor: User | None,
    now: datetime,
) -> bool:
    require_grantable(db, subscription=subscription, promo=promo, now=now)
    before = subscription.expires_at if from_plan is not None else None
    if promo.plan is not None and (
        plan_move(subscription=subscription, plan=promo.plan, now=now)
        == PlanMove.RESTART
    ):
        plan = promo.plan
        days = promo.grant_days or plan.period_days
        subscription.plan_id = plan.id
        subscription.plan = plan
        subscription.term_started_at = now
        subscription.expires_at = now + timedelta(days=days)
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.canceled_at = None
        subscription.ended_at = None
        subscription.extra_pages += promo.grant_pages
        db.flush()
        record_change(
            db,
            subscription=subscription,
            kind=HistoryKind.PROMO,
            from_plan=from_plan,
            move=PlanMove.RESTART,
            days=days,
            expires_before=before,
            now=now,
            actor=actor,
            reason=promo.code,
        )
        return True
    if promo.grant_days:
        if subscription.expires_at <= now:
            subscription.term_started_at = now
        subscription.expires_at = max(subscription.expires_at, now) + timedelta(
            days=promo.grant_days
        )
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.canceled_at = None
        subscription.ended_at = None
    if promo.grant_pages:
        subscription.extra_pages += promo.grant_pages
    plan_changed = promo.plan_id is not None and promo.plan_id != subscription.plan_id
    if plan_changed and promo.plan is not None:
        subscription.plan_id = promo.plan.id
        subscription.plan = promo.plan
    db.flush()
    if promo.grant_days or plan_changed:
        record_change(
            db,
            subscription=subscription,
            kind=HistoryKind.PROMO,
            from_plan=from_plan,
            move=PlanMove.STACK if from_plan is not None else PlanMove.RESTART,
            days=promo.grant_days,
            expires_before=before,
            now=now,
            actor=actor,
            reason=promo.code,
        )
    return plan_changed
