"""CRM manager seat bills: paying one starts seats and counts as a sale."""

from datetime import timedelta

from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.constants import (
    InvoiceKind,
    PlanMove,
    SubscriptionStatus,
    WalletChoice,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors.seats import paid_seats, seat_remainder
from app.modules.billing.services.entitlement import insert_invoice, run_plan_seats
from app.modules.billing.services.invoices import apply_payment, price_invoice
from app.modules.crm.models import CrmMember
from app.modules.integrations.models import PageAccount, ProviderConnection
from app.modules.sales.models import SaleSource


def _paid_plan(db: Session) -> tuple[User, Plan, Subscription]:
    now = utcnow()
    owner = User(email="shop@client.test", password="!", date_joined=now)
    plan = Plan(
        code="pro",
        name="Pro",
        price=490000,
        currency="UZS",
        period_days=30,
        max_adsets=10,
        llm_cost_limit_minor=1000,
        crm_seat_price=60000,
    )
    db.add_all([owner, plan])
    db.flush()
    subscription = Subscription(
        owner_id=owner.id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=now - timedelta(days=10),
        expires_at=now + timedelta(days=20),
    )
    db.add(subscription)
    db.commit()
    return owner, plan, subscription


def _page(db: Session, owner: User) -> PageAccount:
    """A page in the cabinet, and its manager already in its free seat."""
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id="fb-seat",
        token_encrypted=b"x",
        token_fingerprint=fingerprint("x"),
    )
    db.add(connection)
    db.flush()
    page = PageAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="page_seat",
        connection_id=connection.id,
        name="Sahifa",
        token_encrypted=b"x",
        token_fingerprint="p-seat",
        is_active=True,
        is_current=True,
    )
    db.add(page)
    holder = User(email="free@shop.test", password="!", date_joined=utcnow())
    db.add(holder)
    db.flush()
    db.add(
        CrmMember(
            owner_id=owner.id,
            user_id=holder.id,
            page_id=page.id,
            created_at=utcnow() - timedelta(days=1),
        )
    )
    db.flush()
    return page


def test_a_paid_seat_bill_runs_seats_and_moves_no_date(db: Session) -> None:
    owner, plan, subscription = _paid_plan(db)
    expires = subscription.expires_at
    now = utcnow()
    bill = insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=4000000,
        period_days=0,
        expires_at=now + timedelta(hours=1),
        now=now,
        kind=InvoiceKind.SEATS,
        seats=2,
        seats_minor=4000000,
    )

    apply_payment(db, invoice=bill, now=now)
    db.commit()
    db.expire_all()

    bill = db.get(Invoice, bill.id)
    assert bill is not None and bill.status == "paid"
    assert bill.applied_days == 0
    assert bill.seats_from == now and bill.seats_until == expires
    assert db.get(Subscription, subscription.id).expires_at == expires  # type: ignore[union-attr]
    assert paid_seats(db, owner=owner, at=now + timedelta(days=1)) == 2
    assert seat_remainder(db, owner=owner, currency="UZS", now=now) == 4000000
    sale = db.scalar(select(SaleSource).where(SaleSource.invoice_id == bill.id))
    assert sale is not None and sale.source == "self"


def test_a_seat_bill_stops_at_its_own_days(db: Session) -> None:
    owner, plan, _ = _paid_plan(db)
    now = utcnow()
    bill = insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=60000,
        period_days=0,
        expires_at=now + timedelta(hours=1),
        now=now,
        kind=InvoiceKind.SEATS,
        seats=1,
        seats_minor=60000,
        seats_days=7,
    )
    apply_payment(db, invoice=bill, now=now)
    db.commit()
    assert bill.seats_until == now + timedelta(days=7)


def test_a_restart_ends_the_seats_it_credited(db: Session) -> None:
    owner, plan, subscription = _paid_plan(db)
    now = utcnow()
    old = insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=60000,
        period_days=0,
        expires_at=now + timedelta(hours=1),
        now=now - timedelta(days=1),
        kind=InvoiceKind.SEATS,
        seats=1,
        seats_minor=60000,
    )
    apply_payment(db, invoice=old, now=now - timedelta(days=1))
    renewal = insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=490000,
        period_days=30,
        expires_at=now + timedelta(hours=1),
        now=now,
        seats=1,
        seats_minor=60000,
    )
    run_plan_seats(
        db,
        invoice=renewal,
        subscription=subscription,
        move=PlanMove.RESTART,
        before=subscription.expires_at,
        now=now,
    )
    db.flush()
    db.refresh(old)
    assert old.seats_until == now
    assert renewal.seats_from == now
    assert renewal.seats_until == subscription.expires_at


def test_a_renewal_carries_only_the_seats_somebody_sits_in(db: Session) -> None:
    owner, plan, _ = _paid_plan(db)
    now = utcnow()
    bought = insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=120000,
        period_days=0,
        expires_at=now + timedelta(hours=1),
        now=now,
        kind=InvoiceKind.SEATS,
        seats=2,
        seats_minor=120000,
    )
    apply_payment(db, invoice=bought, now=now)
    manager = User(email="manager@shop.test", password="!", date_joined=now)
    db.add(manager)
    db.flush()
    # A manager on a page of the cabinet: one with no page cannot work, so
    # needs no seat.
    page = _page(db, owner)
    db.add(CrmMember(owner_id=owner.id, user_id=manager.id, page_id=page.id))
    db.commit()

    renewal = insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=490000,
        period_days=30,
        expires_at=now + timedelta(hours=1),
        now=now,
    )
    priced = price_invoice(
        db, invoice=renewal, promo_code="", wallet=WalletChoice.KEEP, now=now
    )
    assert priced.seats == 1
    assert priced.seats_minor == 6000000
    assert priced.amount_minor == 490000 + 6000000

    again = price_invoice(
        db, invoice=priced, promo_code="", wallet=WalletChoice.KEEP, now=now
    )
    assert again.amount_minor == 490000 + 6000000
