"""CRM manager seats bought on top of a plan: the twin of the pages ledger.

A paid bill with ``seats`` names how many it bought and the stretch they
run, so the seats paid for at any moment are a sum over bills. A renewal
carries only the seats somebody sits in.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.common.money import decimal_places, to_minor
from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceStatus
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors.pages import prorate


def seat_price_minor(*, plan: Plan) -> int:
    return int(to_minor(amount=str(plan.crm_seat_price), currency=plan.currency))


def plan_seats_minor(*, plan: Plan, count: int) -> int:
    return prorate(
        price_minor=seat_price_minor(plan=plan),
        count=count,
        days=plan.period_days,
        currency=plan.currency,
    )


def running_seat_bills_query(*, owner: User, at: datetime) -> Select[Any]:
    return select(Invoice).where(
        Invoice.owner_id == owner.id,
        Invoice.status == InvoiceStatus.PAID,
        Invoice.seats > 0,
        Invoice.seats_from <= at,
        Invoice.seats_until > at,
    )


def paid_seats(db: Session, *, owner: User, at: datetime) -> int:
    total = db.scalar(
        select(func.sum(Invoice.seats)).where(
            Invoice.owner_id == owner.id,
            Invoice.status == InvoiceStatus.PAID,
            Invoice.seats > 0,
            Invoice.seats_from <= at,
            Invoice.seats_until > at,
        )
    )
    return int(total or 0)


def carried_seats(
    db: Session, *, owner: User, subscription: Subscription | None
) -> int:
    """The seats a renewal carries: those running at its last moment, but no
    more than the managers the free page seats leave waiting."""
    from app.modules.crm.selectors import unseated_count

    if subscription is None:
        return 0
    last = subscription.expires_at - timedelta(seconds=1)
    return min(
        paid_seats(db, owner=owner, at=last),
        unseated_count(db, owner=owner, subscription=subscription),
    )


def seat_remainder(db: Session, *, owner: User, currency: str, now: datetime) -> int:
    """What the unused days of the running seats are worth, in ``currency``."""
    minor = 0
    for bill in db.scalars(
        running_seat_bills_query(owner=owner, at=now).where(
            Invoice.currency == currency
        )
    ):
        if bill.seats_from is None or bill.seats_until is None:
            continue
        covered = max(
            1, round((bill.seats_until - bill.seats_from).total_seconds() / 86_400)
        )
        seconds = (bill.seats_until - now).total_seconds()
        left = min(covered, max(0, -int(-seconds // 86_400)))
        minor += bill.seats_minor * left // covered
    unit = 10 ** int(decimal_places(currency))
    return int(minor - minor % unit)
