"""Sales kinds of lead, the order «Lid olish» gives them, taking a lead by
phone, the report by kind, and the 2026-11-20 migration of the cards, against
PostgreSQL."""

import importlib
from datetime import timedelta
from typing import Any

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing.models import Invoice, Subscription
from app.modules.boards.models import BoardCard, BoardCardEvent
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_offer import _buys_start, _card
from tests.pg.test_boards_sales import URL, _client, _detail, _live, _paid, _sweep

TAKE = f"{URL}/sales/take"
BY_PHONE = f"{URL}/sales/take-by-phone"


def _lead(db: Session, email: str, phone: str, *, minutes_ago: int = 5) -> User:
    person = _client(db, email, minutes_ago=minutes_ago)
    person.phone = phone
    db.commit()
    return person


def _user(db: Session, email: str) -> User:
    person = db.scalar(select(User).where(User.email == email))
    assert person is not None
    return person


def _start_ago(db: Session, owner: User, hours: float) -> None:
    _buys_start(db, owner)
    db.execute(
        update(Invoice)
        .where(Invoice.owner_id == owner.id)
        .values(paid_at=utcnow() - timedelta(hours=hours))
    )
    db.commit()


def _kinds(client: TestClient, head: dict[str, str]) -> dict[str, Any]:
    view = client.get(f"{URL}/boards/sales", headers=head)
    assert view.status_code == 200, view.text
    return view.json()["take"]


def test_lid_olish_gives_start_live_then_ended_then_expired_then_new(
    client: TestClient, db: Session
) -> None:
    _live(db, hours_ago=300)
    fresh = _lead(db, "fresh@shop.test", "+998900000001", minutes_ago=1)
    ended = _lead(db, "ended@shop.test", "+998900000002")
    ten = _lead(db, "ten@shop.test", "+998900000003")
    twenty = _lead(db, "twenty@shop.test", "+998900000004")
    ten_soon = _lead(db, "ten.soon@shop.test", "+998900000005")
    expired = _lead(db, "expired@shop.test", "+998900000006")
    _sweep(db)
    _start_ago(db, ended, 120)
    _start_ago(db, expired, 200)
    # Its Start term ran out yesterday; Ended's still runs.
    db.execute(
        update(Subscription)
        .where(Subscription.owner_id == expired.id)
        .values(expires_at=utcnow() - timedelta(days=1))
    )
    db.commit()
    _start_ago(db, ten, 30)
    _start_ago(db, ten_soon, 90)
    _start_ago(db, twenty, 2)
    _sweep(db)
    assert {_card(db, p).column_code for p in (fresh, ended, ten, twenty)} == {
        "unworked"
    }

    ali = _staff(db, "ali@office.test", Role.SALES)
    take = _kinds(client, ali)
    assert take["queue"] == 6 and take["own"] == 6
    assert [(k["value"], k["count"], k["own"]) for k in take["kinds"]] == [
        ("start_live", 3, True),
        ("start_ended", 1, True),
        ("start_expired", 1, True),
        ("new", 1, True),
    ]
    order = []
    vali = _staff(db, "vali@office.test", Role.SALES)
    for head in (ali, ali, ali, vali, vali, vali):
        card = _detail(client.post(TAKE, headers=head))
        assert card.column == "new_lead"
        order.append((card.client.email, card.taken_as.value if card.taken_as else ""))
    # 20% first; among the 10% ones the one that ends soonest.
    assert order == [
        ("twenty@shop.test", "start_live"),
        ("ten.soon@shop.test", "start_live"),
        ("ten@shop.test", "start_live"),
        ("ended@shop.test", "start_ended"),
        ("expired@shop.test", "start_expired"),
        ("fresh@shop.test", "new"),
    ]
    shown = _detail(client.get(f"{URL}/cards/{_card(db, expired).id}", headers=vali))
    assert shown.kind is not None and shown.kind.label == "Start olgan, tarifi tugagan"


def test_a_manager_takes_own_kinds_first_then_any(
    client: TestClient, db: Session
) -> None:
    _live(db, hours_ago=300)
    starter = _lead(db, "starter@shop.test", "+998900000011")
    newbie = _lead(db, "newbie@shop.test", "+998900000012")
    _sweep(db)
    _start_ago(db, starter, 1)
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    owner = _staff(db, "owner@office.test", Role.OWNER)
    ali_id = _user(db, "ali@office.test").id

    shown = client.get(f"{URL}/boards/sales/kinds", headers=owner)
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert [k["value"] for k in body["kinds"]] == [
        "start_live",
        "start_ended",
        "start_expired",
        "new",
    ]
    assert body["members"][0]["all"] is True
    assert client.get(f"{URL}/boards/sales/kinds", headers=ali).status_code == 404

    put = f"{URL}/boards/sales/kinds/{ali_id}"
    assert client.put(put, json={"kinds": []}, headers=owner).status_code == 422
    bad = client.put(put, json={"kinds": ["vip"]}, headers=owner)
    assert bad.status_code == 422
    assert client.put(put, json={"kinds": ["new"]}, headers=ali).status_code == 404
    saved = client.put(put, json={"kinds": ["new"]}, headers=owner)
    assert saved.status_code == 200, saved.text
    assert saved.json()["kinds"] == ["new"] and saved.json()["all"] is False

    take = _kinds(client, ali)
    assert take["queue"] == 2 and take["own"] == 1
    # Own kind first, though a Start buyer waits.
    first = _detail(client.post(TAKE, headers=ali))
    assert first.client.email == newbie.email
    # None of own left: any kind.
    second = _detail(client.post(TAKE, headers=ali))
    assert second.client.email == starter.email
    assert second.taken_as is not None and second.taken_as.value == "start_live"

    every = client.put(
        put,
        json={"kinds": ["start_live", "start_ended", "start_expired", "new"]},
        headers=owner,
    )
    assert every.json()["all"] is True


def test_take_by_phone_ignores_order_kinds_and_the_limit(
    client: TestClient, db: Session
) -> None:
    _live(db, hours_ago=300)
    for n in range(6):
        _lead(db, f"queue{n}@shop.test", f"+99890100000{n}")
    target = _lead(db, "target@shop.test", "+998901234500", minutes_ago=600)
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    owner = _staff(db, "owner@office.test", Role.OWNER)
    ali_id = _user(db, "ali@office.test").id
    client.put(
        f"{URL}/boards/sales/kinds/{ali_id}",
        json={"kinds": ["start_live"]},
        headers=owner,
    )
    for _ in range(5):
        _detail(client.post(TAKE, headers=ali))
    assert client.post(TAKE, headers=ali).status_code == 409

    # Signed up before the board went live: no card yet; any way of writing.
    got = _detail(client.post(BY_PHONE, json={"phone": "90 123-45-00"}, headers=ali))
    assert got.client.email == target.email and got.column == "new_lead"
    assert got.manager is not None and got.manager.email == "ali@office.test"
    assert got.taken_as is not None and got.taken_as.value == "phone"
    assert got.taken_as.label == "Raqam bilan olingan"
    assert got.history[0].kind == "taken"
    assert got.history[0].body == "Raqam bilan olindi"

    mine = client.post(BY_PHONE, json={"phone": "+998901234500"}, headers=ali)
    assert mine.status_code == 409 and mine.json()["code"] == "lead_is_yours"
    assert mine.json()["detail"] == "Bu lid sizda."
    vali = _staff(db, "vali@office.test", Role.SALES)
    other = client.post(BY_PHONE, json={"phone": "901234500"}, headers=vali)
    assert other.status_code == 409 and other.json()["code"] == "lead_with_other"
    assert other.json()["detail"] == "Bu lid boshqa menejerda."


def test_take_by_phone_refuses_unknown_staff_and_late_buyers(
    client: TestClient, db: Session
) -> None:
    _live(db, hours_ago=300)
    worker = _lead(db, "worker@shop.test", "+998907777777")
    worker.is_staff = True
    late = _lead(db, "late@shop.test", "+998906666666")
    db.commit()
    _sweep(db)
    paid = _paid(db, late)
    paid.paid_at = utcnow() - timedelta(hours=13)
    db.commit()
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    for phone in ("+998905555555", "+998907777777", "+998906666666", "1234"):
        answer = client.post(BY_PHONE, json={"phone": phone}, headers=ali)
        assert answer.status_code == 404, (phone, answer.text)
        assert answer.json()["detail"] == "Bunday lid yo'q."
    support = _staff(db, "sup@office.test", Role.SUPPORT)
    denied = client.post(BY_PHONE, json={"phone": "+998906666666"}, headers=support)
    assert denied.status_code == 404


def test_take_by_phone_reopens_a_closed_lead_and_claims_a_fresh_sale(
    client: TestClient, db: Session
) -> None:
    _live(db, hours_ago=300)
    _lead(db, "closed@shop.test", "+998901111111")
    payer = _lead(db, "payer@shop.test", "+998902222222")
    held = _lead(db, "held@shop.test", "+998903333333")
    _sweep(db)
    vali = _staff(db, "vali@office.test", Role.SALES)
    ali = _staff(db, "ali@office.test", Role.SALES)

    # Closed by Vali: nobody works it, Ali may take it back to life.
    card = _detail(client.post(BY_PHONE, json={"phone": "+998901111111"}, headers=vali))
    shut = client.post(
        f"{URL}/cards/{card.id}/actions",
        json={"action": "close", "reason": "not_needed"},
        headers=vali,
    )
    assert shut.status_code == 200, shut.text
    again = _detail(client.post(BY_PHONE, json={"phone": "+998901111111"}, headers=ali))
    assert again.id == card.id and again.column == "new_lead"
    assert again.closed_at is None and again.manager is not None
    assert again.manager.email == "ali@office.test"

    # Paid two hours ago with nobody on the card: Ali claims the sale.
    bill = _paid(db, payer)
    bill.paid_at = utcnow() - timedelta(hours=2)
    db.commit()
    _sweep(db)
    assert _card(db, payer).column_code == "sold"
    claimed = _detail(
        client.post(BY_PHONE, json={"phone": "+998902222222"}, headers=ali)
    )
    assert claimed.column == "sold" and claimed.manager is not None
    assert claimed.taken_as is not None and claimed.taken_as.value == "phone"
    report = client.get(f"{URL}/boards/sales/report", headers=ali).json()
    assert report["total"]["sold"] == 1
    by_kind = {k["value"]: k for k in report["kinds"]}
    assert by_kind["phone"]["taken"] == 2 and by_kind["phone"]["sold"] == 1
    assert by_kind["phone"]["money"][0]["minor"] == 49000000
    assert by_kind["new"]["taken"] == 0
    assert [k["value"] for k in report["kinds"]] == [
        "start_live",
        "start_ended",
        "start_expired",
        "new",
        "phone",
    ]

    # Paid with a manager on the card: theirs, not a claim.
    held_card = _detail(
        client.post(BY_PHONE, json={"phone": "+998903333333"}, headers=vali)
    )
    _paid(db, held)
    _sweep(db)
    assert held_card.manager is not None
    assert str(_card(db, held).manager_id) == held_card.manager.id
    late = client.post(BY_PHONE, json={"phone": "+998903333333"}, headers=ali)
    assert late.status_code == 409 and late.json()["code"] == "lead_with_other"


def test_the_report_splits_taken_and_sold_by_kind(
    client: TestClient, db: Session
) -> None:
    _live(db, hours_ago=300)
    starter = _lead(db, "starter@shop.test", "+998904444441")
    _lead(db, "newbie@shop.test", "+998904444442")
    _sweep(db)
    _start_ago(db, starter, 1)
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    _detail(client.post(TAKE, headers=ali))
    _detail(client.post(TAKE, headers=ali))
    _paid(db, starter)
    _sweep(db)
    owner = _staff(db, "owner@office.test", Role.OWNER)
    report = client.get(f"{URL}/boards/sales/report", headers=owner).json()
    by_kind = {k["value"]: k for k in report["kinds"]}
    assert (by_kind["start_live"]["taken"], by_kind["start_live"]["sold"]) == (1, 1)
    assert by_kind["start_live"]["rate"] == 100
    assert (by_kind["new"]["taken"], by_kind["new"]["sold"]) == (1, 0)
    row = next(
        r
        for r in report["staff"]
        if r["staff"] and r["staff"]["email"] == "ali@office.test"
    )
    assert {k["value"]: k["taken"] for k in row["kinds"]}["start_live"] == 1


def _migrate(db: Session) -> None:
    module = importlib.import_module("migrations.versions.20261120_0070_sales_kinds")
    connection = db.connection()
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
    db.commit()


def test_the_migration_puts_start_cards_back_by_the_new_rule(
    client: TestClient, db: Session
) -> None:
    _live(db, hours_ago=300)
    people = {
        name: _lead(db, f"{name}@shop.test", f"+99890500000{n}")
        for n, name in enumerate(
            ("nobody", "untouched", "missed", "talked", "shut", "shut_talked", "plain")
        )
    }
    _sweep(db)
    for name in ("shut", "shut_talked"):
        _start_ago(db, people[name], 120)
    ali = _staff(db, "ali@office.test", Role.SALES)
    ali_id = _user(db, "ali@office.test").id
    now = utcnow()
    states = {
        "nobody": dict(column_code="discount_20", manager_id=None),
        "untouched": dict(column_code="discount_10", manager_id=ali_id),
        "missed": dict(
            column_code="discount_20", manager_id=ali_id, contact_mark="no_contact"
        ),
        "talked": dict(
            column_code="discount_20", manager_id=ali_id, contact_mark="contacted"
        ),
        "shut": dict(
            column_code="closed",
            manager_id=None,
            closed_at=now,
            close_reason="offer_ended",
        ),
        "shut_talked": dict(
            column_code="closed",
            manager_id=ali_id,
            contact_mark="contacted",
            closed_at=now,
            close_reason="offer_ended",
        ),
        # No Start: the talk's discount ended it; stays closed.
        "plain": dict(
            column_code="closed",
            manager_id=ali_id,
            contact_mark="contacted",
            closed_at=now,
            close_reason="offer_ended",
        ),
    }
    for name, values in states.items():
        db.execute(
            update(BoardCard)
            .where(BoardCard.owner_id == people[name].id)
            .values(**values)
        )
    db.commit()

    _migrate(db)
    _migrate(db)
    db.expire_all()
    got = {
        name: (
            _card(db, person).column_code,
            _card(db, person).manager_id == ali_id,
            _card(db, person).closed_at is None,
        )
        for name, person in people.items()
    }
    assert got == {
        "nobody": ("unworked", False, True),
        "untouched": ("new_lead", True, True),
        "missed": ("no_contact", True, True),
        "talked": ("discount_20", True, True),
        "shut": ("unworked", False, True),
        "shut_talked": ("contacted", True, True),
        "plain": ("closed", True, False),
    }
    shut = _card(db, people["shut"])
    assert shut.close_reason == ""
    lines = db.scalars(
        select(BoardCardEvent.kind).where(BoardCardEvent.card_id == shut.id)
    ).all()
    assert lines.count("moved") == 1
    taken = _detail(client.post(TAKE, headers=ali))
    assert taken.client.email in {"nobody@shop.test", "shut@shop.test"}


def test_a_start_buyer_whose_term_ran_out_without_a_card_becomes_a_lead(
    client: TestClient, db: Session
) -> None:
    """Paid Start before the board went live: never carded. Once the Start
    term runs out the client waits in Ishlanmagan as «tarifi tugagan»; a
    card a manager holds or closed is left alone, and so are buyers."""
    _live(db, hours_ago=1)
    old = _lead(db, "old@shop.test", "+998908000001", minutes_ago=60 * 24 * 30)
    running = _lead(db, "running@shop.test", "+998908000002", minutes_ago=60 * 24 * 30)
    bought = _lead(db, "bought@shop.test", "+998908000003", minutes_ago=60 * 24 * 30)
    held = _lead(db, "held@shop.test", "+998908000004", minutes_ago=60 * 24 * 30)
    for person in (old, running, bought, held):
        _start_ago(db, person, 24 * 10)
    ended = utcnow() - timedelta(days=3)
    for person in (old, bought, held):
        db.execute(
            update(Subscription)
            .where(Subscription.owner_id == person.id)
            .values(expires_at=ended)
        )
    db.commit()
    _paid(db, bought)
    _staff(db, "ali@office.test", Role.SALES)
    ali = _user(db, "ali@office.test")
    db.add(
        BoardCard(
            board="sales",
            owner_id=held.id,
            manager_id=ali.id,
            column_code="closed",
            closed_at=utcnow(),
            close_reason="not_needed",
            opened_at=utcnow(),
            column_since=utcnow(),
            reasons=[],
        )
    )
    db.commit()

    _sweep(db)
    db.expire_all()
    card = _card(db, old)
    assert card.column_code == "unworked" and card.manager_id is None
    assert card.opened_at == ended
    # The full plan made the buyer a sale, not a lead in Ishlanmagan.
    paid_card = db.scalar(select(BoardCard).where(BoardCard.owner_id == bought.id))
    assert paid_card is None or paid_card.column_code != "unworked"
    assert _card(db, held).column_code == "closed"
    assert db.scalar(select(BoardCard).where(BoardCard.owner_id == running.id)) is None

    lines = db.scalars(
        select(BoardCardEvent.body).where(BoardCardEvent.card_id == card.id)
    ).all()
    assert lines == ["Start tarifi tugadi"]
    # Once: the card keeps them out of the rule.
    assert _sweep(db)[0] == 0
    head = _staff(db, "sanjar@office.test", Role.SALES)
    taken = _detail(client.post(TAKE, headers=head))
    assert taken.client.email == old.email
    assert taken.taken_as is not None and taken.taken_as.value == "start_expired"
