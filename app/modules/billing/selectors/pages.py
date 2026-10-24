import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.money import decimal_places, to_minor
from app.modules.accounts.models import User
from app.modules.billing.constants import (
    MAX_PAGES_PER_PURCHASE,
    PAGE_PRICE_DAYS,
    InvoiceStatus,
    PlanMove,
    SubscriptionStatus,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors.subscription import (
    days_left,
    has_ever_subscribed,
    live_subscription,
)

PREPARATION_PAGES = 1


@dataclass(frozen=True, slots=True)
class PageOffer:
    plan: Plan | None
    price_minor: int
    days: int
    until: datetime | None
    sellable: bool
    needs_plan: bool


def page_price_minor(*, plan: Plan) -> int:
    return int(to_minor(amount=str(plan.extra_page_price), currency=plan.currency))


def prorate(*, price_minor: int, count: int, days: int, currency: str) -> int:
    minor = price_minor * count * days // PAGE_PRICE_DAYS
    unit = 10 ** decimal_places(currency)
    return minor - minor % unit


def plan_pages_minor(*, plan: Plan, count: int) -> int:
    return prorate(
        price_minor=page_price_minor(plan=plan),
        count=count,
        days=plan.period_days,
        currency=plan.currency,
    )


def page_offer(db: Session, *, owner: User, now: datetime) -> PageOffer:
    subscription = live_subscription(db, owner=owner)
    if subscription is None or subscription.status == SubscriptionStatus.TRIAL:
        return PageOffer(None, 0, 0, None, sellable=False, needs_plan=True)
    plan = subscription.plan
    days = days_left(subscription=subscription, now=now) or 0
    price = page_price_minor(plan=plan)
    return PageOffer(
        plan=plan,
        price_minor=price,
        days=days,
        until=subscription.expires_at,
        sellable=price > 0 and days > 0,
        needs_plan=days <= 0,
    )


def running_page_bills_query(*, owner: User, at: datetime) -> Select[tuple[Invoice]]:
    return select(Invoice).where(
        Invoice.owner_id == owner.id,
        Invoice.status == InvoiceStatus.PAID,
        Invoice.pages > 0,
        Invoice.pages_from <= at,
        Invoice.pages_until > at,
    )


def running_page_bills(db: Session, *, owner: User, at: datetime) -> list[Invoice]:
    return list(db.scalars(running_page_bills_query(owner=owner, at=at)))


def paid_pages(db: Session, *, owner: User, at: datetime) -> int:
    total = db.scalar(
        select(func.sum(Invoice.pages)).where(
            Invoice.owner_id == owner.id,
            Invoice.status == InvoiceStatus.PAID,
            Invoice.pages > 0,
            Invoice.pages_from <= at,
            Invoice.pages_until > at,
        )
    )
    return int(total or 0)


def carried_pages(
    db: Session, *, owner: User, subscription: Subscription | None
) -> int:
    if subscription is None:
        return 0
    return paid_pages(
        db, owner=owner, at=subscription.expires_at - timedelta(seconds=1)
    )


def page_remainder(db: Session, *, owner: User, currency: str, now: datetime) -> int:
    minor = 0
    for bill in db.scalars(
        running_page_bills_query(owner=owner, at=now).where(
            Invoice.currency == currency
        )
    ):
        if bill.pages_from is None or bill.pages_until is None:
            continue
        covered = max(
            1, round((bill.pages_until - bill.pages_from).total_seconds() / 86_400)
        )
        seconds = (bill.pages_until - now).total_seconds()
        left = min(covered, max(0, -int(-seconds // 86_400)))
        minor += bill.pages_minor * left // covered
    unit = 10 ** decimal_places(currency)
    return minor - minor % unit


@dataclass(frozen=True, slots=True)
class Capacity:
    pages: int
    google_accounts: int


def capacity(db: Session, *, owner: User) -> Capacity:
    subscription = live_subscription(db, owner=owner)
    if subscription is None:
        pages = 0 if has_ever_subscribed(db, owner=owner) else PREPARATION_PAGES
        return Capacity(pages=pages, google_accounts=0)
    return Capacity(
        pages=subscription_pages(db, owner=owner, subscription=subscription),
        google_accounts=subscription.plan.included_google_accounts,
    )


def subscription_pages(db: Session, *, owner: User, subscription: Subscription) -> int:
    bought = paid_pages(db, owner=owner, at=utcnow())
    return subscription.plan.included_pages + subscription.extra_pages + bought


@dataclass(frozen=True, slots=True)
class Term:
    days_left: int
    days_total: int

    @property
    def percent_left(self) -> int:
        if self.days_total <= 0:
            return 0
        return min(100, self.days_left * 100 // self.days_total)


@dataclass(frozen=True, slots=True)
class PageMix:
    included: int
    granted: int
    bought: int


@dataclass(frozen=True, slots=True)
class PageQuote:
    count: int
    total_minor: int
    wallet_minor: int

    @property
    def due_minor(self) -> int:
        return self.total_minor - self.wallet_minor


def term(*, subscription: Subscription | None, now: datetime) -> Term | None:
    if subscription is None:
        return None
    start = subscription.term_started_at or subscription.started_at
    total = math.ceil((subscription.expires_at - start).total_seconds() / 86_400)
    left = days_left(subscription=subscription, now=now) or 0
    return Term(days_left=left, days_total=max(total, left))


def page_mix(
    db: Session, *, owner: User, subscription: Subscription | None, now: datetime
) -> PageMix:
    if subscription is None:
        return PageMix(included=0, granted=0, bought=0)
    return PageMix(
        included=subscription.plan.included_pages,
        granted=subscription.extra_pages,
        bought=paid_pages(db, owner=owner, at=now),
    )


def offer_ends_at(*, offer: Any, now: datetime) -> datetime:
    current = offer.switch.current
    start = now
    if offer.switch.move == PlanMove.STACK and current is not None:
        start = max(current.expires_at, now)
    return start + timedelta(days=offer.plan.period_days)


def page_quotes(*, offer: PageOffer, wallet_minor: int) -> tuple[PageQuote, ...]:
    if not offer.sellable or offer.plan is None:
        return ()
    currency = offer.plan.currency
    quotes = []
    for count in range(1, MAX_PAGES_PER_PURCHASE + 1):
        total = prorate(
            price_minor=offer.price_minor,
            count=count,
            days=offer.days,
            currency=currency,
        )
        quotes.append(PageQuote(count, total, min(wallet_minor, total)))
    return tuple(quotes)


def offer_as_dict(offer: PageOffer) -> dict[str, Any]:
    return {
        "plan_code": offer.plan.code if offer.plan else "",
        "currency": offer.plan.currency if offer.plan else "",
        "price_minor": offer.price_minor,
        "days": offer.days,
        "until": offer.until.isoformat() if offer.until else None,
        "sellable": offer.sellable,
        "needs_plan": offer.needs_plan,
    }


def quote_as_dict(quote: PageQuote) -> dict[str, int]:
    return {
        "count": quote.count,
        "total_minor": quote.total_minor,
        "wallet_minor": quote.wallet_minor,
        "due_minor": quote.due_minor,
    }
