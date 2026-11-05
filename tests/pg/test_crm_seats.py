"""CRM manager seats the owner buys and hands out: a seat bill bought from the
cabinet, the seats overview, and a manager moved to another pair with the
seat that pair has free."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceKind
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors import open_page_bill
from app.modules.billing.services import apply_payment
from app.modules.crm.backfill import assign_pairs
from app.modules.crm.models import CrmCard, CrmMember, CrmStage
from tests.pg.test_crm_pairs import _auth, _world


def _seated_world(db: Session) -> dict[str, object]:
    """Two pages on one account; both managers on page 1, where the older sits
    in the free seat and the younger waits. Seats sell at 60 000 UZS."""
    world = _world(db)
    assign_pairs(db)
    owner = world["owner"]
    plan = db.scalar(
        select(Plan)
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(Subscription.owner_id == owner.id)  # type: ignore[attr-defined]
    )
    assert plan is not None
    plan.currency = "UZS"
    plan.crm_seat_price = 60000
    db.commit()
    return world


def _member(db: Session, user: User) -> CrmMember:
    member = db.scalar(select(CrmMember).where(CrmMember.user_id == user.id))
    assert member is not None
    return member


def _buy_seat(client: TestClient, db: Session, owner: User) -> Invoice:
    """Bill one seat through the API, then land it as the provider would."""
    asked = client.post(
        "/api/v1/billing/seats", json={"count": 1}, headers=_auth(owner)
    )
    # No provider chosen: the bill stays open, waiting to be paid.
    assert asked.status_code == 400, asked.text
    bill = open_page_bill(db, owner=owner, now=utcnow(), kind=InvoiceKind.SEATS)
    assert bill is not None and bill.seats == 1
    apply_payment(db, invoice=bill, now=utcnow())
    db.commit()
    return bill


def test_a_seat_is_bought_and_seats_the_waiting_manager(
    client: TestClient, db: Session
) -> None:
    world = _seated_world(db)
    owner = world["owner"]
    auth = _auth(owner)  # type: ignore[arg-type]

    offer = client.get("/api/v1/billing/seats", headers=auth)
    assert offer.status_code == 200, offer.text
    body = offer.json()
    assert body["offer"]["sellable"] is True
    assert body["offer"]["price_minor"] == 6000000
    assert len(body["quotes"]) == body["max_seats_per_purchase"] == 10
    # 29 of 30 days left: one seat costs its share.
    assert 0 < body["quotes"][0]["total_minor"] < 6000000
    assert (body["free"], body["free_used"], body["paid"], body["waiting"]) == (
        2,
        1,
        0,
        1,
    )

    too_many = client.post("/api/v1/billing/seats", json={"count": 11}, headers=auth)
    assert too_many.status_code == 422

    bill = _buy_seat(client, db, owner)  # type: ignore[arg-type]
    assert bill.status == "paid" and bill.seats_until is not None

    seats = client.get("/api/v1/crm/settings/seats", headers=auth)
    assert seats.status_code == 200, seats.text
    got = seats.json()
    assert (got["paid"], got["paid_used"], got["paid_open"], got["waiting"]) == (
        1,
        1,
        0,
        0,
    )
    kinds = {row["member"]["user"]["email"]: row["seat"] for row in got["members"]}
    assert kinds == {"m1@example.com": "free", "m2@example.com": "paid"}
    assert {row["pair"] for row in got["members"]} == {"page_1:act_1"}

    # The manager who waited may open the board now.
    mine = client.get("/api/v1/crm", headers=_auth(world["managers"][1]))  # type: ignore[index]
    assert mine.status_code == 200, mine.text


def test_seats_are_not_sold_on_a_trial(client: TestClient, db: Session) -> None:
    world = _seated_world(db)
    owner = world["owner"]
    subscription = db.scalar(
        select(Subscription).where(Subscription.owner_id == owner.id)  # type: ignore[attr-defined]
    )
    subscription.status = "trial"  # type: ignore[union-attr]
    db.commit()

    auth = _auth(owner)  # type: ignore[arg-type]
    offer = client.get("/api/v1/billing/seats", headers=auth).json()
    assert offer["offer"]["needs_plan"] is True and offer["quotes"] == []
    refused = client.post("/api/v1/billing/seats", json={"count": 1}, headers=auth)
    assert refused.status_code == 400
    assert refused.json()["code"] == "seats_need_paid_plan"


def test_a_manager_moves_to_another_pair_with_its_free_seat(
    client: TestClient, db: Session
) -> None:
    world = _seated_world(db)
    owner = world["owner"]
    older, younger = world["managers"]  # type: ignore[misc]
    page_2 = world["pages"][1]  # type: ignore[index]
    cards = world["cards"]
    auth = _auth(owner)  # type: ignore[arg-type]
    younger_member = _member(db, younger)

    # The younger, waiting on page 1, takes page 2's empty free seat; their
    # open card goes back to page 1's first column, the closed one stays.
    moved = client.post(
        f"/api/v1/crm/settings/members/{younger_member.id}/move",
        params={"pair": "page_1:act_1"},
        json={"pair": "page_2:act_1"},
        headers=auth,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["seated"] is True
    assert moved.json()["pair"] == "page_2:act_1"
    assert moved.json()["cards_released"] == 1
    db.expire_all()
    assert _member(db, younger).page_id == page_2.id
    released = db.get(CrmCard, cards["first"].id)  # type: ignore[index]
    assert released.assignee_id is None  # type: ignore[union-attr]
    first = db.get(CrmStage, released.stage_id)  # type: ignore[union-attr]
    assert first.kind == "new" and first.page_id == released.page_id  # type: ignore[union-attr]
    closed = db.get(CrmCard, cards["second"].id)  # type: ignore[index]
    assert closed.assignee_id == younger.id  # type: ignore[union-attr]
    assert client.get("/api/v1/crm", headers=_auth(younger)).json()["pair"] == (
        "page_2:act_1"
    )

    # The older one would take page 2's free seat and leave the younger
    # without one: refused, and nothing moves.
    older_member = _member(db, older)
    refused = client.post(
        f"/api/v1/crm/settings/members/{older_member.id}/move",
        params={"pair": "page_1:act_1"},
        json={"pair": "page_2:act_1"},
        headers=auth,
    )
    assert refused.status_code == 400
    assert refused.json()["code"] == "no_seat_there"
    db.expire_all()
    assert _member(db, older).page_id != page_2.id

    # With a seat bought, both fit on page 2.
    _buy_seat(client, db, owner)  # type: ignore[arg-type]
    again = client.post(
        f"/api/v1/crm/settings/members/{older_member.id}/move",
        params={"pair": "page_1:act_1"},
        json={"pair": "page_2:act_1"},
        headers=auth,
    )
    assert again.status_code == 200, again.text
    seats = client.get("/api/v1/crm/settings/seats", headers=auth).json()
    kinds = {row["member"]["user"]["email"]: row["seat"] for row in seats["members"]}
    assert kinds == {"m1@example.com": "free", "m2@example.com": "paid"}
    assert {row["pair"] for row in seats["members"]} == {"page_2:act_1"}


def test_a_move_names_a_pair_of_the_owner_and_not_its_own(
    client: TestClient, db: Session
) -> None:
    world = _seated_world(db)
    owner = world["owner"]
    member = _member(db, world["managers"][0])  # type: ignore[index]
    auth = _auth(owner)  # type: ignore[arg-type]
    url = f"/api/v1/crm/settings/members/{member.id}/move"

    same = client.post(
        url,
        params={"pair": "page_1:act_1"},
        json={"pair": "page_1:act_1"},
        headers=auth,
    )
    assert same.status_code == 400 and same.json()["code"] == "same_pair"
    unknown = client.post(
        url,
        params={"pair": "page_1:act_1"},
        json={"pair": "page_9:act_1"},
        headers=auth,
    )
    assert unknown.status_code == 400 and unknown.json()["code"] == "unknown_pair"
    # Asked from the other pair's CRM, the manager is not found there.
    elsewhere = client.post(
        url,
        params={"pair": "page_2:act_1"},
        json={"pair": "page_1:act_1"},
        headers=auth,
    )
    assert elsewhere.status_code == 400 and elsewhere.json()["code"] == "unknown_member"
    # A manager cannot move anybody.
    refused = client.post(
        url,
        json={"pair": "page_2:act_1"},
        headers=_auth(world["managers"][0]),  # type: ignore[index]
    )
    assert refused.status_code == 404
