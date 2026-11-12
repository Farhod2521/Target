"""The Sales board v2 against PostgreSQL: who becomes a lead, «Lid olish»,
the buttons, the lead giving cards out, and a payment closing the card."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.boards import selectors, triggers
from app.modules.boards.constants import Board
from app.modules.boards.models import BoardCard, BoardCardEvent, BoardSetting
from app.modules.boards.schemas import BoardViewOut, CardDetailOut
from app.worker import beat_schedule
from tests.pg.test_boards_me import _staff

URL = "/api/v2/office"


def _live(db: Session, *, hours_ago: int = 1) -> None:
    selectors.ensure_board(db, board=Board.SALES, now=utcnow())
    db.execute(
        update(BoardSetting)
        .where(BoardSetting.board == "sales")
        .values(live_since=utcnow() - timedelta(hours=hours_ago))
    )
    db.commit()


def _client(db: Session, email: str, *, minutes_ago: int = 5, **fields: Any) -> User:
    person = User(
        email=email,
        full_name=email.split("@")[0].title(),
        password="!",
        phone="+998901234567",
        date_joined=utcnow() - timedelta(minutes=minutes_ago),
        **fields,
    )
    db.add(person)
    db.commit()
    return person


def _plan(db: Session) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.code == "standart"))
    if plan is None:
        plan = Plan(
            code="standart",
            name="Standart",
            price=490000,
            currency="UZS",
            period_days=30,
            max_adsets=10,
            llm_cost_limit_minor=1000,
        )
        db.add(plan)
        db.flush()
    return plan


def _paid(db: Session, owner: User, *, status: str = InvoiceStatus.PAID) -> Invoice:
    invoice = Invoice(
        owner_id=owner.id,
        number=f"TA-{str(owner.id)[:8]}",
        plan_id=_plan(db).id,
        amount_minor=49000000,
        currency="UZS",
        period_days=30,
        expires_at=utcnow(),
        status=status,
        paid_at=utcnow() if status == InvoiceStatus.PAID else None,
    )
    db.add(invoice)
    db.commit()
    return invoice


def _sweep(db: Session) -> tuple[int, int]:
    return triggers.sweep_sales(db, now=utcnow())


def _cards(db: Session) -> dict[str, BoardCard]:
    db.expire_all()
    return {
        card.owner.email: card
        for card in db.scalars(select(BoardCard).where(BoardCard.board == "sales"))
    }


def _detail(answer: Any) -> CardDetailOut:
    assert answer.status_code == 200, answer.text
    return CardDetailOut.model_validate(answer.json())


def test_only_first_time_sign_ups_after_the_deploy_become_leads(db: Session) -> None:
    _live(db)
    _client(db, "new@shop.test")
    _client(db, "old@shop.test", minutes_ago=120)
    _client(db, "staff@shop.test", is_staff=True)
    owner = _client(db, "owner@shop.test")
    _client(db, "login@shop.test", crm_owner_id=owner.id)
    _client(db, "blocked@shop.test", is_active=False)
    _paid(db, _client(db, "paid@shop.test"))
    _paid(db, _client(db, "refunded@shop.test"), status=InvoiceStatus.REFUNDED)
    given = _client(db, "given@shop.test")
    db.add(
        Subscription(
            owner_id=given.id,
            plan_id=_plan(db).id,
            status=SubscriptionStatus.ACTIVE,
            extra_pages=0,
            started_at=utcnow(),
            expires_at=utcnow() + timedelta(days=30),
            note="",
        )
    )
    db.commit()

    assert _sweep(db) == (2, 0)
    assert sorted(_cards(db)) == ["new@shop.test", "owner@shop.test"]
    assert {card.column_code for card in _cards(db).values()} == {"unworked"}

    assert _sweep(db) == (0, 0)
    assert db.scalar(select(func.count()).select_from(BoardCardEvent)) == 2


def test_lid_olish_hands_out_the_oldest_lead_once(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _client(db, "first@shop.test", minutes_ago=30)
    _client(db, "second@shop.test", minutes_ago=10)
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    vali = _staff(db, "vali@office.test", Role.SALES)

    one = _detail(client.post(f"{URL}/sales/take", headers=ali))
    two = _detail(client.post(f"{URL}/sales/take", headers=vali))
    assert one.client.email == "first@shop.test" and one.column == "new_lead"
    assert two.client.email == "second@shop.test"
    assert one.manager is not None and one.manager.email == "ali@office.test"
    assert one.history[0].kind == "taken"

    empty = client.post(f"{URL}/sales/take", headers=ali)
    assert empty.status_code == 409 and empty.json()["code"] == "nothing_to_take"


def test_support_does_not_take_leads_the_superuser_and_owner_do(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _client(db, "first@shop.test")
    _sweep(db)

    support = _staff(db, "support@office.test", Role.SUPPORT)
    assert (
        client.get("/api/v2/office/me", headers=support).json()["can"]["take"] is False
    )
    assert client.post(f"{URL}/sales/take", headers=support).status_code == 404

    boss = _staff(db, "boss@office.test", superuser=True)
    assert client.get("/api/v2/office/me", headers=boss).json()["can"]["take"] is True
    card = _detail(client.post(f"{URL}/sales/take", headers=boss))
    assert card.client.email == "first@shop.test" and card.column == "new_lead"
    assert card.manager is not None and card.manager.email == "boss@office.test"

    _client(db, "second@shop.test")
    _sweep(db)
    owner = _staff(db, "owner@office.test", Role.OWNER)
    assert client.get("/api/v2/office/me", headers=owner).json()["can"]["take"] is True
    card = _detail(client.post(f"{URL}/sales/take", headers=owner))
    assert card.client.email == "second@shop.test"
    assert card.manager is not None and card.manager.email == "owner@office.test"


def test_the_buttons_follow_the_column(client: TestClient, db: Session) -> None:
    _live(db)
    _client(db, "first@shop.test")
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))
    press = f"{URL}/cards/{card.id}/actions"

    assert [a.value for a in card.actions] == ["contacted", "no_contact", "close"]
    early = client.post(press, json={"action": "needs_support"}, headers=ali)
    assert early.status_code == 409

    missed = _detail(client.post(press, json={"action": "no_contact"}, headers=ali))
    assert missed.column == "no_contact" and missed.contact_mark == "no_contact"
    assert [a.value for a in missed.actions] == ["contacted", "close"]

    talked = _detail(
        client.post(
            press, json={"action": "contacted", "note": "Ertaga to'laydi"}, headers=ali
        )
    )
    assert talked.column == "contacted" and talked.history[0].body == "Ertaga to'laydi"

    marked = _detail(client.post(press, json={"action": "needs_support"}, headers=ali))
    assert marked.needs_support and marked.column == "contacted"
    again = _detail(client.post(press, json={"action": "needs_support"}, headers=ali))
    assert [h.kind for h in again.history].count("support_on") == 1
    off = _detail(
        client.post(press, json={"action": "needs_support", "on": False}, headers=ali)
    )
    assert not off.needs_support and off.history[0].kind == "support_off"

    assert client.post(press, json={"action": "close"}, headers=ali).status_code == 422
    other = client.post(press, json={"action": "close", "reason": "other"}, headers=ali)
    assert other.status_code == 422 and other.json()["code"] == "note_required"
    closed = _detail(
        client.post(press, json={"action": "close", "reason": "expensive"}, headers=ali)
    )
    assert closed.column == "closed" and closed.close_reason_label == "Qimmat"
    assert closed.actions == [] and closed.closed_at is not None
    assert (
        client.post(press, json={"action": "contacted"}, headers=ali).status_code == 409
    )
    assert client.post(press, json={"action": "jump"}, headers=ali).status_code == 422


def test_a_manager_sees_only_their_own_cards(client: TestClient, db: Session) -> None:
    _live(db)
    _client(db, "first@shop.test", minutes_ago=30)
    _client(db, "second@shop.test", minutes_ago=10)
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    vali = _staff(db, "vali@office.test", Role.SALES)
    mine = _detail(client.post(f"{URL}/sales/take", headers=ali))

    assert client.get(f"{URL}/cards/{mine.id}", headers=vali).status_code == 404
    press = client.post(
        f"{URL}/cards/{mine.id}/actions", json={"action": "contacted"}, headers=vali
    )
    assert press.status_code == 404

    seen = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/sales", headers=vali).json()
    )
    assert [c.code for c in seen.columns] == [
        "new_lead",
        "no_contact",
        "contacted",
        "discount_20",
        "discount_10",
        "no_discount",
        "sold",
    ]
    assert all(c.total == 0 for c in seen.columns)
    own = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/sales", headers=ali).json()
    )
    assert (
        own.columns[0].total == 1
        and own.columns[0].cards[0].client.email == "first@shop.test"
    )


def test_the_lead_sees_the_queue_and_gives_cards_out(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _client(db, "first@shop.test", minutes_ago=30)
    _client(db, "second@shop.test", minutes_ago=10)
    _sweep(db)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)
    ali = _staff(db, "ali@office.test", Role.SALES)
    support = _staff(db, "support@office.test", Role.SUPPORT)

    seen = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/sales", headers=lead).json()
    )
    queue = seen.columns[0]
    assert queue.code == "unworked" and queue.total == 2
    assert [c.client.email for c in queue.cards] == [
        "first@shop.test",
        "second@shop.test",
    ]
    found = client.get(
        f"{URL}/boards/sales", params={"q": "secon"}, headers=lead
    ).json()
    assert [c["client"]["email"] for c in found["columns"][0]["cards"]] == [
        "second@shop.test"
    ]

    people = client.get(f"{URL}/boards/sales/staff", headers=lead).json()["staff"]
    assert [p["email"] for p in people] == ["ali@office.test", "rahbar@office.test"]
    assert client.get(f"{URL}/boards/sales/staff", headers=ali).status_code == 404

    card = queue.cards[0].id
    ali_id = next(p["id"] for p in people if p["email"] == "ali@office.test")
    given = _detail(
        client.post(
            f"{URL}/cards/{card}/assign", json={"staff_id": ali_id}, headers=lead
        )
    )
    assert given.column == "new_lead" and given.manager is not None
    assert given.history[0].kind == "assigned"
    assert client.get(f"{URL}/cards/{card}", headers=ali).status_code == 200

    support_id = db.scalar(select(User.id).where(User.email == "support@office.test"))
    refused = client.post(
        f"{URL}/cards/{card}/assign", json={"staff_id": str(support_id)}, headers=lead
    )
    assert refused.status_code == 422 and refused.json()["code"] == "not_on_board"
    assert (
        client.post(
            f"{URL}/cards/{card}/assign", json={"staff_id": ali_id}, headers=ali
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{URL}/cards/{card}/assign", json={"staff_id": ali_id}, headers=support
        ).status_code
        == 404
    )

    back = _detail(
        client.post(f"{URL}/cards/{card}/assign", json={"staff_id": None}, headers=lead)
    )
    assert back.column == "unworked" and back.manager is None
    assert client.get(f"{URL}/cards/{card}", headers=ali).status_code == 404


def test_a_note_goes_into_the_history(client: TestClient, db: Session) -> None:
    _live(db)
    _client(db, "first@shop.test")
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))

    noted = _detail(
        client.post(
            f"{URL}/cards/{card.id}/notes",
            json={"body": "Qayta qo'ng'iroq"},
            headers=ali,
        )
    )
    assert noted.history[0].kind == "note" and noted.history[0].actor is not None
    blank = client.post(
        f"{URL}/cards/{card.id}/notes", json={"body": "   "}, headers=ali
    )
    assert blank.status_code == 422


def test_a_payment_moves_the_card_to_sotildi_even_from_yopildi(
    client: TestClient, db: Session
) -> None:
    _live(db)
    queued = _client(db, "queued@shop.test", minutes_ago=30)
    closed = _client(db, "closed@shop.test", minutes_ago=10)
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    _detail(client.post(f"{URL}/sales/take", headers=ali))
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))
    client.post(
        f"{URL}/cards/{card.id}/actions",
        json={"action": "close", "reason": "expensive"},
        headers=ali,
    )
    _paid(db, queued, status=InvoiceStatus.PENDING)

    assert _sweep(db) == (0, 0)
    _paid(db, closed)
    db.execute(
        update(Invoice)
        .where(Invoice.owner_id == queued.id)
        .values(status="paid", paid_at=utcnow())
    )
    db.commit()

    assert _sweep(db) == (0, 2)
    cards = _cards(db)
    assert {cards[e].column_code for e in ("queued@shop.test", "closed@shop.test")} == {
        "sold"
    }
    assert cards["closed@shop.test"].closed_at is not None
    assert _sweep(db) == (0, 0)

    seen = _detail(client.get(f"{URL}/cards/{card.id}", headers=ali))
    assert seen.history[0].kind == "sold" and seen.actions == []


def test_a_sold_card_moved_out_by_hand_does_not_stop_the_sweep(
    client: TestClient, db: Session
) -> None:
    """The second ``sold`` line would break the one-fact-once index and roll
    back every other card's move with it."""
    _live(db)
    moved = _client(db, "moved@shop.test", minutes_ago=30)
    later = _client(db, "later@shop.test", minutes_ago=10)
    _sweep(db)
    _paid(db, moved)
    assert _sweep(db) == (0, 1)
    card = _cards(db)["moved@shop.test"]
    boss = _staff(db, "boss@office.test", superuser=True)
    answer = client.post(
        f"{URL}/cards/{card.id}/move",
        json={"column": "closed", "reason": "Qaytarildi"},
        headers=boss,
    )
    assert answer.status_code == 200, answer.text
    _paid(db, later)

    assert _sweep(db) == (0, 1)
    cards = _cards(db)
    assert cards["later@shop.test"].column_code == "sold"
    assert cards["moved@shop.test"].column_code == "closed"


def test_the_sweep_is_on_the_beat_every_minute() -> None:
    entries = {e["task"]: e for e in beat_schedule().values()}
    entry = entries["app.modules.boards.tasks.sweep_sales_board_task"]
    assert str(entry["schedule"]._orig_minute) == "*"
