"""A plan renewal with what was bought on the period that ends: the price on
the screen is the price billed, every extra page and manager seat is listed,
and what the owner unticks is let go only once the bill is paid."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import tasks as ads_tasks
from app.modules.ads.models import Campaign, LapseHold
from app.modules.ads.selectors.lapse import lapse_targets, open_hold
from app.modules.ads.services import settle_lapse
from app.modules.audit.models import ActionLog
from app.modules.billing.constants import InvoiceKind
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.services import apply_payment
from app.modules.billing.services.entitlement import insert_invoice
from app.modules.crm.models import CrmMember
from app.modules.integrations.models import PageAccount
from tests.pg.test_crm_pairs import _auth
from tests.pg.test_crm_seats import _buy_seat, _seated_world


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    stops: list[str] = []
    monkeypatch.setattr(ads_tasks.stop_page_hold_task, "delay", stops.append)
    # A paid plan bill also wakes a lapsed subscription's adverts.
    monkeypatch.setattr(ads_tasks.resume_after_payment_task, "delay", lambda _: None)
    # Changes to Meta are only queued here, never sent.
    monkeypatch.setattr(ads_tasks.apply_change_task, "delay", lambda _: None)
    monkeypatch.setattr(ads_tasks.apply_delete_task, "delay", lambda _: None)
    return stops


def _world(client: TestClient, db: Session) -> dict[str, Any]:
    """Pro at 490 000 for 30 days with one page in the plan: page 2 sits in a
    bought page slot (100 000), and the younger manager in a bought seat
    (60 000)."""
    world = _seated_world(db)
    owner = world["owner"]
    plan = db.scalar(select(Plan))
    assert plan is not None
    plan.code, plan.name, plan.price = "pro", "Pro", 490000
    plan.period_days, plan.is_active = 30, True
    plan.included_pages, plan.extra_page_price = 1, 100000
    now = utcnow()
    pages = insert_invoice(
        db,
        owner=owner,
        plan=plan,
        amount_minor=1,
        period_days=0,
        expires_at=now + timedelta(hours=1),
        now=now,
        kind=InvoiceKind.PAGES,
        pages=1,
        pages_minor=1,
    )
    apply_payment(db, invoice=pages, now=now)
    db.commit()
    _buy_seat(client, db, owner)
    world["plan"] = plan
    return world


def _quote(client: TestClient, owner: User, **drops: Any) -> dict[str, Any]:
    got = client.get(
        "/api/v1/billing", params={"plan": "pro", **drops}, headers=_auth(owner)
    )
    assert got.status_code == 200, got.text
    return got.json()


def _bill(client: TestClient, db: Session, owner: User, **drops: Any) -> Invoice:
    asked = client.post(
        "/api/v1/billing/checkout", json={"plan": "pro", **drops}, headers=_auth(owner)
    )
    # No provider chosen: the bill stays open, priced.
    assert asked.status_code == 400, asked.text
    db.expire_all()
    bill = db.scalar(
        select(Invoice)
        .where(Invoice.owner_id == owner.id, Invoice.kind == InvoiceKind.PLAN)
        .order_by(Invoice.created_at.desc())
    )
    assert bill is not None
    return bill


def test_the_renewal_lists_and_bills_every_page_and_seat(
    client: TestClient, db: Session
) -> None:
    world = _world(client, db)
    owner = world["owner"]

    body = _quote(client, owner)
    chosen, renewal = body["chosen"], body["renewal"]
    assert (chosen["pages"], chosen["pages_minor"]) == (1, 10000000)
    assert (chosen["seats"], chosen["seats_minor"]) == (1, 6000000)
    assert chosen["due_minor"] == 49000000 + 10000000 + 6000000
    assert renewal["pages"]["paid_used"] == 1 and renewal["pages"]["empty"] == 0
    assert {line["name"] for line in renewal["pages"]["lines"]} == {
        "Sahifa 1",
        "Sahifa 2",
    }
    assert [line["email"] for line in renewal["seats"]["lines"]] == ["m2@example.com"]
    assert renewal["seats"]["lines"][0]["page"] == "Sahifa 1"

    bill = _bill(client, db, owner)
    assert bill.amount_minor == chosen["due_minor"]
    assert (bill.pages, bill.seats) == (1, 1)


def test_unticked_page_and_seat_leave_the_bill_and_go_once_paid(
    client: TestClient, db: Session, queued: list[str]
) -> None:
    world = _world(client, db)
    owner = world["owner"]
    page_2 = world["pages"][1]
    younger = db.scalar(
        select(CrmMember).where(CrmMember.user_id == world["managers"][1].id)
    )
    assert younger is not None
    younger_id = younger.id
    drops = {"drop_pages": [str(page_2.id)], "drop_members": [str(younger_id)]}

    body = _quote(client, owner, **drops)
    chosen = body["chosen"]
    assert (chosen["pages"], chosen["seats"]) == (0, 0)
    assert chosen["due_minor"] == 49000000
    dropped = [line["dropped"] for line in body["renewal"]["seats"]["lines"]]
    assert dropped == [True]

    bill = _bill(client, db, owner, **drops)
    assert bill.amount_minor == 49000000
    assert bill.drop_page_ids == [str(page_2.id)]
    # Priced is not paid: nothing goes yet.
    db.expire_all()
    assert db.get(PageAccount, page_2.id).is_active  # type: ignore[union-attr]
    assert db.get(CrmMember, younger_id).is_active  # type: ignore[union-attr]

    apply_payment(db, invoice=bill, now=utcnow())
    db.commit()
    db.expire_all()
    assert not db.get(PageAccount, page_2.id).is_active  # type: ignore[union-attr]
    gone = db.get(CrmMember, younger_id)
    assert gone is None or not gone.is_active
    hold = db.scalar(select(LapseHold).where(LapseHold.page_id == page_2.id))
    assert hold is not None and hold.is_open
    assert hold.delete_after - hold.started_at == timedelta(days=3)
    assert queued == [str(hold.id)]
    # It is no lapsed subscription: the cabinet's lapse notice stays quiet.
    assert open_hold(db, owner=owner) is None
    seats = client.get("/api/v1/crm/settings/seats", headers=_auth(owner)).json()
    assert [row["member"]["user"]["email"] for row in seats["members"]] == [
        "m1@example.com"
    ]


def test_a_drop_names_only_what_is_paid_for(client: TestClient, db: Session) -> None:
    world = _world(client, db)
    owner = world["owner"]
    pages = world["pages"]
    older = db.scalar(
        select(CrmMember).where(CrmMember.user_id == world["managers"][0].id)
    )
    assert older is not None
    auth = _auth(owner)

    def refused(**drops: Any) -> str:
        got = client.get(
            "/api/v1/billing", params={"plan": "pro", **drops}, headers=auth
        )
        assert got.status_code == 400, got.text
        return str(got.json()["code"])

    assert refused(drop_members=[str(older.id)]) == "unknown_drop_member"
    assert refused(drop_pages=[str(p.id) for p in pages]) == "too_many_drop_pages"
    assert refused(drop_pages=["not-a-page"]) == "unknown_drop_page"
    assert refused(drop_empty_pages=1) == "too_many_drop_empty"


def test_a_let_go_page_holds_only_its_own_adverts(
    client: TestClient, db: Session, queued: list[str]
) -> None:
    world = _world(client, db)
    owner = world["owner"]
    account, page_2 = world["account"], world["pages"][1]
    for n in (1, 2):
        db.add(
            Campaign(
                owner_id=owner.id,
                ad_account_id=account.id,
                external_id=f"c_{n}",
                name=f"Kampaniya {n}",
                provider=PROVIDER,
            )
        )
    db.commit()
    bill = _bill(client, db, owner, drop_pages=[str(page_2.id)])
    apply_payment(db, invoice=bill, now=utcnow())
    db.commit()
    hold = db.scalar(select(LapseHold).where(LapseHold.page_id == page_2.id))
    assert hold is not None
    assert [
        t.external_id for t in lapse_targets(db, owner=owner, page_id=page_2.id)
    ] == ["c_2"]

    # Before the grace days end page 2's campaign is paused, page 1's not
    # touched; then it is deleted and the hold closed.
    assert settle_lapse(db, hold=hold, now=utcnow()) == "held"
    later = hold.delete_after + timedelta(minutes=1)
    assert settle_lapse(db, hold=hold, now=later) == "removed"
    assert hold.deleted_at is not None
    asked = {
        (log.action, log.target_external_id)
        for log in db.scalars(select(ActionLog).where(ActionLog.owner_id == owner.id))
    }
    assert asked == {("pause", "c_2"), ("delete_campaign", "c_2")}


def test_a_page_back_in_the_cabinet_keeps_its_adverts(
    client: TestClient, db: Session, queued: list[str]
) -> None:
    world = _world(client, db)
    owner = world["owner"]
    page_2 = world["pages"][1]
    bill = _bill(client, db, owner, drop_pages=[str(page_2.id)])
    apply_payment(db, invoice=bill, now=utcnow())
    db.commit()
    hold = db.scalar(select(LapseHold).where(LapseHold.page_id == page_2.id))
    assert hold is not None
    page_2 = db.get(PageAccount, page_2.id)
    page_2.is_active = True  # type: ignore[union-attr]
    db.commit()
    later = hold.delete_after + timedelta(minutes=1)
    assert settle_lapse(db, hold=hold, now=later) == "kept"
    assert hold.resumed_at is not None and hold.deleted_at is None


def test_a_switch_bills_what_it_quotes_and_credits_seats_once(
    client: TestClient, db: Session, queued: list[str]
) -> None:
    world = _world(client, db)
    owner = world["owner"]
    # A paid Pro period with its seat, then a switch to a dearer Biznes.
    paid = _bill(client, db, owner)
    apply_payment(db, invoice=paid, now=utcnow())
    db.add(
        Plan(
            code="biznes",
            name="Biznes",
            price=1990000,
            currency="UZS",
            period_days=30,
            is_active=True,
            max_adsets=10,
            llm_cost_limit_minor=0,
            included_pages=1,
            extra_page_price=100000,
            crm_seat_price=60000,
        )
    )
    db.commit()

    got = client.get(
        "/api/v1/billing", params={"plan": "biznes"}, headers=_auth(owner)
    ).json()
    chosen = got["chosen"]
    assert chosen["move"] == "restart"
    asked = client.post(
        "/api/v1/billing/checkout", json={"plan": "biznes"}, headers=_auth(owner)
    )
    assert asked.status_code == 400, asked.text
    db.expire_all()
    bill = db.scalar(
        select(Invoice)
        .join(Plan, Plan.id == Invoice.plan_id)
        .where(Plan.code == "biznes")
    )
    assert bill is not None
    assert bill.amount_minor == chosen["due_minor"]
    # Every credit together is no more than what is left of the money paid.
    subscription = db.scalar(select(Subscription))
    assert subscription is not None
    paid_total = sum(
        invoice.amount_minor + invoice.wallet_minor
        for invoice in db.scalars(
            select(Invoice).where(
                Invoice.status == "paid", Invoice.owner_id == owner.id
            )
        )
    )
    credits = (
        chosen["credit_minor"]
        + chosen["page_credit_minor"]
        + chosen["seat_credit_minor"]
    )
    assert 0 < credits <= paid_total
