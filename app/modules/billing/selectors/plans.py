from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from paykit import registry
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.common.money import decimal_places, to_minor
from app.modules.accounts.models import User
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceKind,
    InvoiceStatus,
    PagesChoice,
    PlanMove,
    SubscriptionStatus,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors.pages import (
    carried_pages,
    page_remainder,
    plan_pages_minor,
)
from app.modules.billing.selectors.subscription import (
    days_left,
    latest_subscription,
    running_subscription,
)


def without_spent(
    *, plans: Select[tuple[Plan]], owner: User | None
) -> Select[tuple[Plan]]:
    if owner is None:
        return plans
    spent = select(Invoice.plan_id).where(
        Invoice.owner_id == owner.id,
        Invoice.status == InvoiceStatus.PAID,
        Invoice.kind == InvoiceKind.PLAN,
    )
    return plans.where(~(Plan.is_one_time.is_(True) & Plan.id.in_(spent)))


def sellable_plans(db: Session, *, owner: User | None = None) -> list[Plan]:
    query = without_spent(
        plans=select(Plan).where(Plan.is_active.is_(True), Plan.price > 0), owner=owner
    )
    return list(db.scalars(query.order_by(Plan.sort_order, Plan.code)))


def has_bought_plan(db: Session, *, owner: User, plan: Plan) -> bool:
    return (
        db.scalar(
            select(Invoice.id)
            .where(
                Invoice.owner_id == owner.id,
                Invoice.plan_id == plan.id,
                Invoice.status == InvoiceStatus.PAID,
                Invoice.kind == InvoiceKind.PLAN,
            )
            .limit(1)
        )
        is not None
    )


def every_plan(db: Session) -> list[Plan]:
    return list(
        db.scalars(
            select(Plan).order_by(Plan.is_active.desc(), Plan.sort_order, Plan.code)
        )
    )


def public_plans(db: Session, *, owner: User | None = None) -> list[Plan]:
    query = without_spent(
        plans=select(Plan).where(Plan.is_active.is_(True)), owner=owner
    )
    return list(db.scalars(query.order_by(Plan.sort_order, Plan.code)))


def sellable_plan(db: Session, *, code: str, owner: User | None = None) -> Plan | None:
    return next(
        (plan for plan in sellable_plans(db, owner=owner) if plan.code == code), None
    )


def featured_plan(plans: Sequence[Plan]) -> Plan | None:
    priced = sorted((plan for plan in plans if plan.price > 0), key=lambda p: p.price)
    if len(priced) < 2:
        return None
    return priced[(len(priced) - 1) // 2]


@dataclass(frozen=True, slots=True)
class PaymentChoice:
    name: str
    label: str


def payment_providers() -> list[dict[str, str]]:
    return [{"name": name, "label": name.title()} for name in registry.available()]


def payments_configured() -> bool:
    return bool(registry.available())


@dataclass(frozen=True, slots=True)
class TierLine:
    text: str
    is_heading: bool


@dataclass(frozen=True, slots=True)
class TierSheet:
    lines: tuple[TierLine, ...]
    highlights: tuple[str, ...]
    per_page: int | None


def tier_sheet(*, plan: Plan) -> TierSheet:
    lines: list[TierLine] = []
    highlights: list[str] = []
    for raw in plan.features.splitlines():
        text = raw.strip()
        if text.startswith("*"):
            if body := text.lstrip("*").strip():
                highlights.append(body)
        elif text.startswith("#"):
            if body := text.lstrip("#").strip():
                lines.append(TierLine(text=body, is_heading=True))
        elif text:
            lines.append(TierLine(text=text, is_heading=False))
    per_page = None
    if plan.included_pages > 1 and plan.price:
        share = plan.price // plan.included_pages
        step = 10 ** max(len(str(share)) - 3, 0)
        per_page = round(share / step) * step
    return TierSheet(
        lines=tuple(lines), highlights=tuple(highlights), per_page=per_page
    )


@dataclass(frozen=True, slots=True)
class PlanSwitch:
    move: PlanMove
    current: Subscription | None
    credit_minor: int = 0
    credit_days: int = 0

    @property
    def until(self) -> datetime | None:
        if self.move != PlanMove.WAIT or self.current is None:
            return None
        return self.current.expires_at


@dataclass(frozen=True, slots=True)
class Offer:
    plan: Plan
    switch: PlanSwitch
    price_minor: int
    discount_minor: int
    credit_minor: int
    wallet_minor: int
    pages: int = 0
    pages_minor: int = 0
    page_credit_minor: int = 0

    @property
    def due_minor(self) -> int:
        return self.due_without_wallet_minor - self.wallet_minor

    @property
    def due_without_wallet_minor(self) -> int:
        return (
            self.price_minor
            - self.discount_minor
            + self.pages_minor
            - self.credit_minor
            - self.page_credit_minor
        )


def _cheaper(*, plan: Plan, than: Plan) -> bool:
    if plan.price == 0:
        return than.price > 0
    return plan.currency == than.currency and plan.price < than.price


def plan_move(
    *, subscription: Subscription | None, plan: Plan, now: datetime
) -> PlanMove:
    if (
        subscription is None
        or subscription.status not in LIVE_SUBSCRIPTION_STATUSES
        or subscription.expires_at <= now
        or subscription.status == SubscriptionStatus.TRIAL
        or subscription.plan_id == plan.id
    ):
        return PlanMove.STACK
    if _cheaper(plan=plan, than=subscription.plan):
        return PlanMove.WAIT
    return PlanMove.RESTART


def plan_switch(db: Session, *, owner: User, plan: Plan, now: datetime) -> PlanSwitch:
    current = running_subscription(db, owner=owner, now=now)
    return _switch(db, owner=owner, current=current, plan=plan, now=now, credit=None)


def remainder(
    db: Session, *, owner: User, subscription: Subscription, now: datetime
) -> tuple[int, int]:
    days = days_left(subscription=subscription, now=now) or 0
    currency = subscription.plan.currency
    query = select(Invoice).where(
        Invoice.owner_id == owner.id,
        Invoice.subscription_id == subscription.id,
        Invoice.status == InvoiceStatus.PAID,
        Invoice.applied_days > 0,
        Invoice.currency == currency,
    )
    if subscription.term_started_at is not None:
        query = query.where(Invoice.paid_at >= subscription.term_started_at)
    left, minor = days, 0
    for bill in db.scalars(query.order_by(Invoice.paid_at.desc())):
        if not left:
            break
        taken = min(left, bill.applied_days)
        worth = (
            bill.amount_minor + bill.wallet_minor + bill.credit_minor - bill.pages_minor
        )
        minor += worth * taken // bill.applied_days
        left -= taken
    unit = 10 ** decimal_places(currency)
    return minor - minor % unit, days - left


def _switch(
    db: Session,
    *,
    owner: User,
    current: Subscription | None,
    plan: Plan,
    now: datetime,
    credit: tuple[int, int] | None,
) -> PlanSwitch:
    move = plan_move(subscription=current, plan=plan, now=now)
    if move != PlanMove.RESTART or current is None:
        return PlanSwitch(move=move, current=current)
    if current.plan.currency != plan.currency:
        return PlanSwitch(move=move, current=current)
    minor, days = credit or remainder(db, owner=owner, subscription=current, now=now)
    if minor > int(to_minor(amount=str(plan.price), currency=plan.currency)):
        return PlanSwitch(move=PlanMove.WAIT, current=current)
    return PlanSwitch(move=move, current=current, credit_minor=minor, credit_days=days)


def checkout_offers(
    db: Session,
    *,
    owner: User,
    plans: list[Plan],
    discounts: dict[str, int],
    wallets: dict[str, int],
    now: datetime,
    pages: PagesChoice = PagesChoice.KEEP,
) -> dict[str, Offer]:
    current = running_subscription(db, owner=owner, now=now)
    credit: tuple[int, int] | None = None
    page_credit = 0
    if current is not None and current.status != SubscriptionStatus.TRIAL:
        credit = remainder(db, owner=owner, subscription=current, now=now)
        page_credit = page_remainder(
            db, owner=owner, currency=current.plan.currency, now=now
        )
    carried = (
        carried_pages(
            db,
            owner=owner,
            subscription=current or latest_subscription(db, owner=owner),
        )
        if pages == PagesChoice.KEEP
        else 0
    )
    offers: dict[str, Offer] = {}
    for plan in plans:
        switch = _switch(
            db, owner=owner, current=current, plan=plan, now=now, credit=credit
        )
        offers[plan.code] = _offer(
            plan=plan,
            switch=switch,
            discount_minor=discounts.get(plan.code, 0),
            wallet_minor=wallets.get(plan.currency, 0),
            pages=carried,
            page_credit_minor=page_credit,
        )
    return offers


def _offer(
    *,
    plan: Plan,
    switch: PlanSwitch,
    discount_minor: int,
    wallet_minor: int,
    pages: int,
    page_credit_minor: int,
) -> Offer:
    price = int(to_minor(amount=str(plan.price), currency=plan.currency))
    if switch.move == PlanMove.WAIT:
        wallet_minor = pages = 0
    after_code = max(0, price - discount_minor)
    pages_minor = plan_pages_minor(plan=plan, count=pages)
    gross = after_code + pages_minor
    credit = min(switch.credit_minor, gross)
    page_credit = (
        min(page_credit_minor, gross - credit) if switch.move == PlanMove.RESTART else 0
    )
    return Offer(
        plan=plan,
        switch=switch,
        price_minor=price,
        discount_minor=price - after_code,
        credit_minor=credit,
        wallet_minor=min(max(0, wallet_minor), gross - credit - page_credit),
        pages=pages if pages_minor else 0,
        pages_minor=pages_minor,
        page_credit_minor=page_credit,
    )
