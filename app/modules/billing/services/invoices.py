"""Bills: opening, pricing, discounting, settling, paying and giving back."""

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

from paykit import (
    AMOUNT_MISMATCH,
    INVOICE_NOT_FOUND,
    INVOICE_NOT_PAYABLE,
    Allowed,
    CallbackRequest,
    Checkout,
    CheckoutRequest,
    InvoiceNumber,
    MinorUnits,
    Outcome,
    Refusal,
    Refused,
    registry,
)
from paykit.errors import PaymentError, ProviderNotRegistered
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.common.money import decimal_places, to_minor
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.billing.constants import (
    INVOICE_TTL_HOURS,
    MAX_PAGES_PER_PURCHASE,
    PAYABLE_INVOICE_STATUSES,
    HistoryKind,
    InvoiceKind,
    InvoiceStatus,
    ManualMethod,
    PagesChoice,
    PlanMove,
    RedemptionStatus,
    WalletChoice,
)
from app.modules.billing.exceptions import (
    CheaperPlanWaits,
    InvoiceNotPayable,
    NothingToExtend,
    PageCountOutOfRange,
    PagesNeedPaidPlan,
    PagesNotSold,
    PaymentAmountMissing,
    PaymentUnavailable,
    PlanAlreadyBought,
    PlanNotSellable,
    ReasonRequired,
    ReceiptNotOrphaned,
)
from app.modules.billing.models import (
    Invoice,
    PaymentTransaction,
    Plan,
    PromoCode,
    PromoRedemption,
    Subscription,
)
from app.modules.billing.selectors import (
    PlanSwitch,
    carried_pages,
    discount_quote,
    has_bought_plan,
    invoice_by_number,
    latest_subscription,
    locked_invoice,
    movable_discounts,
    open_invoices,
    open_page_bill,
    page_offer,
    page_remainder,
    payable_invoice,
    plan_pages_minor,
    plan_switch,
    prorate,
    running_subscription,
)
from app.modules.billing.selectors.seats import (
    carried_seats,
    plan_seats_minor,
    seat_remainder,
)
from app.modules.billing.services.entitlement import (
    insert_invoice,
    land_pages,
    land_plan,
    land_seats,
    lift_wallet,
    locked_entitlement,
    open_entitlement,
    payer,
    record_change,
    release_discount,
    resume_lapsed,
    run_plan_pages,
    run_plan_seats,
)

logger = logging.getLogger(__name__)


def payability_refusal(
    *, invoice: Invoice, amount_minor: int | None, now: datetime
) -> Refusal | None:
    if amount_minor is not None and amount_minor != invoice.amount_minor:
        return AMOUNT_MISMATCH
    if invoice.status not in PAYABLE_INVOICE_STATUSES:
        return INVOICE_NOT_PAYABLE
    if invoice.expires_at <= now:
        return INVOICE_NOT_PAYABLE
    return None


def check_invoice(db: Session, *, request: CallbackRequest, now: datetime) -> Outcome:
    invoice = invoice_by_number(db, number=request.number or "")
    if invoice is None:
        return Refused(reason=INVOICE_NOT_FOUND)
    refusal = payability_refusal(
        invoice=invoice, amount_minor=request.amount_minor, now=now
    )
    if refusal is not None:
        return Refused(reason=refusal, detail=invoice.status)
    return Allowed()


def checkout_for(
    *, invoice: Invoice, provider: str, return_url: str, language: str, now: datetime
) -> Checkout:
    if invoice.status not in PAYABLE_INVOICE_STATUSES or invoice.expires_at <= now:
        raise InvoiceNotPayable
    try:
        adapter = registry.get(provider)
    except ProviderNotRegistered as exc:
        raise PaymentUnavailable from exc
    try:
        return adapter.checkout(
            request=CheckoutRequest(
                number=InvoiceNumber(invoice.number),
                amount_minor=MinorUnits(invoice.amount_minor),
                decimal_places=decimal_places(invoice.currency),
                return_url=return_url,
                language=language,
                currency=invoice.currency,
                description=_receipt_line(invoice),
                ttl_seconds=max(60, int((invoice.expires_at - now).total_seconds())),
            )
        )
    except PaymentError as exc:
        logger.warning(
            "checkout could not be opened",
            extra={"provider": provider, "invoice": invoice.number, "reason": str(exc)},
        )
        raise PaymentUnavailable from exc


def _receipt_line(invoice: Invoice) -> str:
    """What the fiscal receipt names the purchase as."""
    plan = invoice.plan.name if invoice.plan is not None else ""
    if invoice.kind == InvoiceKind.PAGES:
        return f"TargetologAI: qo'shimcha sahifa ({invoice.pages})"
    if invoice.kind == InvoiceKind.SEATS:
        return f"TargetologAI: CRM menejeri o'rni ({invoice.seats})"
    return f"TargetologAI obunasi: {plan}, {invoice.period_days} kun" if plan else ""


def create_invoice(db: Session, *, owner: User, plan: Plan, now: datetime) -> Invoice:
    if not plan.is_active or plan.price <= 0:
        raise PlanNotSellable
    if plan.is_one_time and has_bought_plan(db, owner=owner, plan=plan):
        raise PlanAlreadyBought
    until = plan_switch(db, owner=owner, plan=plan, now=now).until
    if until is not None:
        raise CheaperPlanWaits(until=until)
    existing = payable_invoice(db, owner=owner, plan=plan, now=now)
    if existing is not None:
        return existing
    return insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=int(to_minor(amount=str(plan.price), currency=plan.currency)),
        period_days=plan.period_days,
        expires_at=now + timedelta(hours=INVOICE_TTL_HOURS),
        now=now,
    )


def create_page_invoice(
    db: Session, *, owner: User, count: int, wallet: WalletChoice, now: datetime
) -> Invoice:
    from app.modules.referrals.services import hold_wallet

    if not 1 <= count <= MAX_PAGES_PER_PURCHASE:
        raise PageCountOutOfRange(limit=MAX_PAGES_PER_PURCHASE)
    offer = page_offer(db, owner=owner, now=now)
    if offer.plan is None or offer.needs_plan:
        raise PagesNeedPaidPlan
    amount = prorate(
        price_minor=offer.price_minor,
        count=count,
        days=offer.days,
        currency=offer.plan.currency,
    )
    if not offer.sellable or amount <= 0:
        raise PagesNotSold
    lift_wallet(db, owner=owner, now=now)
    existing = open_page_bill(db, owner=owner, now=now)
    locked = (
        locked_invoice(db, number=existing.number) if existing is not None else None
    )
    if locked is None:
        invoice = insert_invoice(
            db,
            owner=owner,
            plan=offer.plan,
            amount_minor=amount,
            period_days=0,
            expires_at=now + timedelta(hours=INVOICE_TTL_HOURS),
            now=now,
            kind=InvoiceKind.PAGES,
            pages=count,
            pages_minor=amount,
        )
    else:
        invoice = locked
        invoice.plan_id = offer.plan.id
        invoice.currency = offer.plan.currency
        invoice.pages = count
        invoice.pages_minor = amount
        invoice.amount_minor = amount
        db.flush()
    spent = hold_wallet(
        db,
        invoice=invoice,
        amount_minor=amount if wallet == WalletChoice.USE else 0,
        now=now,
    )
    invoice.wallet_minor = spent
    invoice.amount_minor = amount - spent
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.INVOICE_PRICED,
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "number": invoice.number,
            "kind": invoice.kind,
            "pages": invoice.pages,
            "amount_minor": invoice.amount_minor,
            "wallet_minor": invoice.wallet_minor,
            "currency": invoice.currency,
        },
        occurred_at=now,
    )
    return invoice


def _payable_locked(db: Session, *, invoice: Invoice, now: datetime) -> Invoice:
    locked = locked_invoice(db, number=invoice.number)
    if locked is None:
        raise InvoiceNotPayable
    if payability_refusal(invoice=locked, amount_minor=None, now=now) is not None:
        raise InvoiceNotPayable
    return locked


def _redemption_on(db: Session, invoice: Invoice) -> PromoRedemption | None:
    return db.scalar(
        select(PromoRedemption).where(PromoRedemption.invoice_id == invoice.id)
    )


def apply_discount(
    db: Session, *, invoice: Invoice, code: str, now: datetime
) -> PromoRedemption:
    locked = _payable_locked(db, invoice=invoice, now=now)
    owner = payer(locked)
    current = _redemption_on(db, locked)
    base = locked.amount_minor + (current.discount_minor if current else 0)
    quote = discount_quote(
        db, owner=owner, code=code, base_minor=base, currency=locked.currency, now=now
    )
    if current is not None and current.promo_id == quote.promo.id:
        return current
    _lift_elsewhere(db, owner=owner, promo=quote.promo, keep=locked, now=now)
    if current is not None:
        release_discount(db, redemption=current, invoice=locked, now=now)
    locked.amount_minor = quote.total_minor
    redemption = PromoRedemption(
        owner_id=owner.id,
        promo_id=quote.promo.id,
        invoice_id=locked.id,
        status=RedemptionStatus.APPROVED,
        discount_minor=quote.discount_minor,
        granted_days=0,
        granted_pages=0,
        decision_note="",
        redeemed_at=now,
    )
    db.add(redemption)
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PROMO_REDEEMED,
        aggregate_type="invoice",
        aggregate_id=locked.id,
        payload={
            "number": locked.number,
            "code": quote.promo.code,
            "discount_minor": redemption.discount_minor,
            "amount_minor": locked.amount_minor,
            "currency": locked.currency,
        },
        occurred_at=now,
    )
    return redemption


def _lift_elsewhere(
    db: Session, *, owner: User, promo: PromoCode, keep: Invoice, now: datetime
) -> None:
    for moved in movable_discounts(db, owner=owner, promo=promo):
        if (
            moved.invoice_id is None
            or moved.invoice_id == keep.id
            or moved.invoice is None
        ):
            continue
        other = locked_invoice(db, number=moved.invoice.number)
        if other is None or other.status != InvoiceStatus.PENDING:
            continue
        release_discount(db, redemption=moved, invoice=other, now=now)


def drop_discount(db: Session, *, invoice: Invoice, now: datetime) -> Invoice:
    locked = locked_invoice(db, number=invoice.number)
    if locked is None or locked.status != InvoiceStatus.PENDING:
        return invoice
    current = _redemption_on(db, locked)
    if current is not None:
        release_discount(db, redemption=current, invoice=locked, now=now)
    return locked


def price_invoice(
    db: Session,
    *,
    invoice: Invoice,
    promo_code: str,
    wallet: WalletChoice,
    now: datetime,
    pages: PagesChoice = PagesChoice.KEEP,
) -> Invoice:
    from app.modules.referrals.services import hold_wallet

    locked = _payable_locked(db, invoice=invoice, now=now)
    owner = payer(locked)
    lift_wallet(db, owner=owner, now=now)
    db.refresh(locked, ["amount_minor", "wallet_minor"])
    locked.amount_minor += locked.credit_minor - locked.pages_minor - locked.seats_minor
    locked.credit_minor = locked.pages = locked.pages_minor = 0
    locked.seats = locked.seats_minor = 0
    db.flush()
    if promo_code:
        apply_discount(db, invoice=locked, code=promo_code, now=now)
    else:
        drop_discount(db, invoice=locked, now=now)
    db.refresh(locked, ["amount_minor"])
    switch = plan_switch(db, owner=owner, plan=locked.plan, now=now)
    if switch.until is not None:
        raise CheaperPlanWaits(until=switch.until)
    if pages == PagesChoice.KEEP:
        current = running_subscription(db, owner=owner, now=now)
        count = carried_pages(
            db,
            owner=owner,
            subscription=current or latest_subscription(db, owner=owner),
        )
        minor = plan_pages_minor(plan=locked.plan, count=count)
        if minor > 0:
            locked.pages = count
            locked.pages_minor = minor
            locked.amount_minor += minor
    _add_seats(db, invoice=locked, owner=owner, now=now)
    credit = _credit(db, invoice=locked, switch=switch, now=now)
    wanted = locked.amount_minor - credit if wallet == WalletChoice.USE else 0
    spent = hold_wallet(db, invoice=locked, amount_minor=wanted, now=now)
    locked.credit_minor = credit
    locked.wallet_minor = spent
    locked.amount_minor -= credit + spent
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.INVOICE_PRICED,
        aggregate_type="invoice",
        aggregate_id=locked.id,
        payload={
            "number": locked.number,
            "amount_minor": locked.amount_minor,
            "credit_minor": locked.credit_minor,
            "wallet_minor": locked.wallet_minor,
            "pages": locked.pages,
            "pages_minor": locked.pages_minor,
            "seats": locked.seats,
            "seats_minor": locked.seats_minor,
            "currency": locked.currency,
        },
        occurred_at=now,
    )
    return locked


def _add_seats(db: Session, *, invoice: Invoice, owner: User, now: datetime) -> None:
    """Renew the seats somebody sits in on this bill. Always, unlike the pages:
    taking a manager off the team is how one stops paying for a seat."""
    current = running_subscription(db, owner=owner, now=now)
    count = carried_seats(
        db, owner=owner, subscription=current or latest_subscription(db, owner=owner)
    )
    minor = plan_seats_minor(plan=invoice.plan, count=count)
    if minor <= 0:
        return
    invoice.seats = count
    invoice.seats_minor = minor
    invoice.amount_minor += minor


def _credit(db: Session, *, invoice: Invoice, switch: PlanSwitch, now: datetime) -> int:
    credit = min(switch.credit_minor, invoice.amount_minor)
    if switch.move != PlanMove.RESTART:
        return credit
    owner = payer(invoice)
    pages = page_remainder(db, owner=owner, currency=invoice.currency, now=now)
    credit += min(pages, invoice.amount_minor - credit)
    seats = seat_remainder(db, owner=owner, currency=invoice.currency, now=now)
    return credit + min(seats, invoice.amount_minor - credit)


def apply_payment(
    db: Session, *, invoice: Invoice, now: datetime, reason: str = ""
) -> Subscription:
    from app.modules.referrals.services import accrue_reward
    from app.modules.sales.services import credit_sale

    if invoice.kind == InvoiceKind.PAGES:
        return land_pages(db, invoice=invoice, now=now)
    if invoice.kind == InvoiceKind.SEATS:
        return land_seats(db, invoice=invoice, now=now)
    owner = payer(invoice)
    subscription = locked_entitlement(db, owner=owner)
    days = invoice.period_days
    before_plan = subscription.plan if subscription is not None else None
    before = subscription.expires_at if subscription is not None else None
    if subscription is None:
        subscription = open_entitlement(
            db, owner=owner, plan=invoice.plan, days=days, now=now
        )
        move = PlanMove.RESTART
    else:
        move = land_plan(
            db, subscription=subscription, plan=invoice.plan, days=days, now=now
        )
    run_plan_pages(
        db,
        invoice=invoice,
        subscription=subscription,
        move=move,
        before=before,
        now=now,
    )
    run_plan_seats(
        db,
        invoice=invoice,
        subscription=subscription,
        move=move,
        before=before,
        now=now,
    )
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = now
    invoice.subscription_id = subscription.id
    invoice.applied_days = days
    db.flush()
    record_change(
        db,
        subscription=subscription,
        kind=HistoryKind.PAID,
        from_plan=before_plan,
        move=move,
        days=days,
        expires_before=before,
        now=now,
        invoice=invoice,
        actor=db.get(User, invoice.recorded_by_id) if invoice.recorded_by_id else None,
        reason=reason,
    )
    accrue_reward(db, invoice=invoice, now=now)
    credit_sale(db, invoice=invoice, now=now)
    resume_lapsed(db, owner_id=str(owner.id))
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PAYMENT_RECEIVED,
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "number": invoice.number,
            "plan": invoice.plan.code,
            "amount_minor": invoice.amount_minor,
            "credit_minor": invoice.credit_minor,
            "wallet_minor": invoice.wallet_minor,
            "pages": invoice.pages,
            "seats": invoice.seats,
            "currency": invoice.currency,
            "days": days,
        },
        occurred_at=now,
    )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.SUBSCRIPTION_ACTIVATED,
        aggregate_type="subscription",
        aggregate_id=subscription.id,
        payload={
            "plan": subscription.plan.code,
            "expires_at": subscription.expires_at.isoformat(),
            "invoice": invoice.number,
        },
        occurred_at=now,
    )
    return subscription


def settle_covered_invoice(
    db: Session, *, invoice: Invoice, now: datetime
) -> Subscription:
    locked = locked_invoice(db, number=invoice.number)
    if (
        locked is None
        or locked.amount_minor != 0
        or payability_refusal(invoice=locked, amount_minor=None, now=now) is not None
    ):
        raise InvoiceNotPayable
    return apply_payment(db, invoice=locked, now=now)


def record_payment(
    db: Session,
    *,
    owner: User,
    plan: Plan,
    amount_minor: int,
    days: int,
    method: ManualMethod,
    reference: str,
    actor: User,
    reason: str,
    now: datetime,
) -> Invoice:
    if not reason.strip():
        raise ReasonRequired
    if amount_minor <= 0:
        raise PaymentAmountMissing
    if days < 0:
        raise NothingToExtend
    if days == 0 and locked_entitlement(db, owner=owner) is None:
        raise NothingToExtend
    switch = plan_switch(db, owner=owner, plan=plan, now=now)
    if switch.until is not None:
        raise CheaperPlanWaits(until=switch.until)
    invoice = insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=amount_minor,
        period_days=days,
        expires_at=now,
        now=now,
        credit_minor=switch.credit_minor,
        manual_method=method,
        pay_reference=reference.strip(),
        recorded_by_id=actor.id,
        note=f"{now:%d.%m.%Y} · {actor.email} · {reason.strip()}",
    )
    apply_payment(db, invoice=invoice, now=now, reason=reason)
    logger.info(
        "payment %s recorded by hand for %s by %s", invoice.number, owner.id, actor.id
    )
    return invoice


def expire_invoices(db: Session, *, now: datetime) -> int:
    numbers = [invoice.number for invoice in open_invoices(db, now=now)]
    closed = 0
    for number in numbers:
        invoice = locked_invoice(db, number=number)
        if (
            invoice is None
            or invoice.status not in PAYABLE_INVOICE_STATUSES
            or invoice.expires_at > now
        ):
            db.rollback()
            continue
        invoice.status = InvoiceStatus.EXPIRED
        db.commit()
        closed += 1
    if closed:
        logger.info("expired unpaid invoices", extra={"count": closed})
    return closed


def keep_receipts(db: Session, *, owner: User) -> int:
    invoices = list(
        db.scalars(
            select(Invoice.id).where(
                Invoice.owner_id == owner.id, Invoice.paid_at.is_not(None)
            )
        )
    )
    if not invoices:
        return 0
    db.execute(
        update(PaymentTransaction)
        .where(
            PaymentTransaction.owner_id == owner.id,
            PaymentTransaction.invoice_id.in_(invoices),
        )
        .values(owner_id=None)
    )
    kept = db.execute(
        update(Invoice)
        .where(Invoice.id.in_(invoices))
        .values(owner_id=None, subscription_id=None, former_email=owner.email)
    ).rowcount
    logger.info("kept %s receipts of %s", kept, owner.id)
    return int(kept)


def attach_receipts(db: Session, *, invoices: Iterable[Invoice], owner: User) -> int:
    ids = [invoice.id for invoice in invoices]
    if db.scalar(
        select(Invoice.id)
        .where(Invoice.id.in_(ids), Invoice.owner_id.is_not(None))
        .limit(1)
    ):
        raise ReceiptNotOrphaned
    db.execute(
        update(PaymentTransaction)
        .where(
            PaymentTransaction.invoice_id.in_(ids),
            PaymentTransaction.owner_id.is_(None),
        )
        .values(owner_id=owner.id)
    )
    attached = db.execute(
        update(Invoice).where(Invoice.id.in_(ids)).values(owner_id=owner.id)
    ).rowcount
    return int(attached)


def attach_by_email(
    db: Session, *, invoices: Iterable[Invoice]
) -> tuple[int, set[str]]:
    by_email: dict[str, list[Invoice]] = {}
    for invoice in invoices:
        if invoice.owner_id is None and invoice.former_email:
            by_email.setdefault(invoice.former_email.lower(), []).append(invoice)
    attached = 0
    missing: set[str] = set()
    for email, kept in by_email.items():
        owner = db.scalar(select(User).where(func.lower(User.email) == email))
        if owner is None:
            missing.add(email)
            continue
        attached += attach_receipts(db, invoices=kept, owner=owner)
    return attached, missing
