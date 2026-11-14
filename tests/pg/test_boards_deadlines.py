"""The boards' deadlines, the columns that need one, cards opened by hand
and the filters, against PostgreSQL."""

from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import InvoiceStatus
from app.modules.billing.models import Invoice
from app.modules.boards import triggers
from app.modules.boards.models import BoardCard
from app.modules.boards.schemas import BoardViewOut, CardDetailOut
from app.modules.supportchat.models import SupportConversation, SupportMessage
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client, _paid, _plan, _sweep
from tests.pg.test_boards_support import _live

URL = "/api/v2/office"


def _detail(answer: Any) -> CardDetailOut:
    assert answer.status_code in (200, 201), answer.text
    return CardDetailOut.model_validate(answer.json())


def _board(
    client: TestClient, board: str, head: dict[str, str], **params: Any
) -> BoardViewOut:
    answer = client.get(f"{URL}/boards/{board}", params=params, headers=head)
    assert answer.status_code == 200, answer.text
    return BoardViewOut.model_validate(answer.json())


def _in(hours: float) -> str:
    return (utcnow() + timedelta(hours=hours)).isoformat()


def _taken(
    client: TestClient, db: Session, email: str = "lead@shop.test"
) -> tuple[CardDetailOut, dict[str, str], User]:
    _live(db)
    owner = _client(db, email)
    _sweep(db)
    ali = _staff(db, f"ali.{email}", Role.SALES)
    return _detail(client.post(f"{URL}/sales/take", headers=ali)), ali, owner


def _bill(
    db: Session, owner: User, *, minutes: int = 30, number: str = "TA-BILL"
) -> Invoice:
    invoice = Invoice(
        owner_id=owner.id,
        number=number,
        plan_id=_plan(db).id,
        amount_minor=49000000,
        currency="UZS",
        period_days=30,
        expires_at=utcnow() + timedelta(minutes=minutes),
        status=InvoiceStatus.PENDING,
    )
    db.add(invoice)
    db.commit()
    return invoice


def test_callback_needs_a_time_and_any_result_ends_it(
    client: TestClient, db: Session
) -> None:
    card, ali, _ = _taken(client, db)
    press = f"{URL}/cards/{card.id}/actions"

    bare = client.post(press, json={"action": "callback"}, headers=ali)
    assert bare.status_code == 422 and bare.json()["code"] == "due_required"
    past = client.post(
        press, json={"action": "callback", "due_at": _in(-2)}, headers=ali
    )
    assert past.status_code == 422 and past.json()["code"] == "due_past"

    later = _detail(
        client.post(
            press,
            json={"action": "callback", "due_at": _in(3), "note": "Ertaga"},
            headers=ali,
        )
    )
    assert later.column == "callback" and later.due_at is not None
    assert not later.overdue
    assert later.history[0].kind == "callback"
    assert (
        later.history[0].body.startswith("Muddat: ")
        and "Ertaga" in later.history[0].body
    )
    button = {a.value: a for a in later.actions}
    assert button["no_contact"].due == "optional" and button["contacted"].due == ""
    assert button["needs_support"].note_required and "release" not in button

    # The talk starts the discount, and the call time is over.
    talked = _detail(client.post(press, json={"action": "contacted"}, headers=ali))
    assert talked.column == "discount_20" and talked.due_at is None


def test_in_a_discount_column_the_buttons_mark_the_card_and_do_not_move_it(
    client: TestClient, db: Session
) -> None:
    card, ali, _ = _taken(client, db)
    press = f"{URL}/cards/{card.id}/actions"
    talked = _detail(client.post(press, json={"action": "contacted"}, headers=ali))
    assert [a.value for a in talked.actions] == [
        "contacted",
        "no_contact",
        "callback",
        "needs_support",
        "close",
    ]

    bare = client.post(press, json={"action": "callback"}, headers=ali)
    assert bare.status_code == 422 and bare.json()["code"] == "due_required"
    timed = _detail(
        client.post(press, json={"action": "callback", "due_at": _in(3)}, headers=ali)
    )
    assert timed.column == "discount_20" and timed.due_at is not None
    assert timed.history[0].kind == "callback" and timed.history[0].to_column == ""
    assert timed.contact_mark == "contacted"

    missed = _detail(client.post(press, json={"action": "no_contact"}, headers=ali))
    assert missed.column == "discount_20" and missed.contact_mark == "no_contact"
    assert missed.attempts == 1 and missed.due_at is None

    again = _detail(client.post(press, json={"action": "contacted"}, headers=ali))
    assert again.column == "discount_20" and again.contact_mark == "contacted"
    assert [h.kind for h in again.history].count("offered") == 1
    assert again.offer is not None and again.offer.started_at == talked.offer.started_at  # type: ignore[union-attr]

    seen = _board(client, "sales", ali)
    lane = next(c for c in seen.columns if c.code == "discount_20")
    assert lane.total == 1 and lane.cards[0].contact_mark == "contacted"

    closed = _detail(
        client.post(press, json={"action": "close", "reason": "expensive"}, headers=ali)
    )
    assert closed.column == "closed" and closed.offer.percent == 0  # type: ignore[union-attr]


def test_the_deadline_is_set_moved_and_taken_off_in_place(
    client: TestClient, db: Session
) -> None:
    card, ali, _ = _taken(client, db)
    other = _staff(db, "vali@office.test", Role.SALES)
    path = f"{URL}/cards/{card.id}/due"

    assert client.put(path, json={"due_at": _in(1)}, headers=other).status_code == 404
    naive = client.put(path, json={"due_at": "2030-01-01T10:00:00"}, headers=ali)
    assert naive.status_code == 422 and naive.json()["code"] == "due_invalid"

    kept = _detail(
        client.put(path, json={"due_at": _in(1), "note": "Qo'ng'iroq"}, headers=ali)
    )
    assert kept.column == "new_lead" and kept.due_at is not None
    assert kept.history[0].kind == "due_set" and "Qo'ng'iroq" in kept.history[0].body
    off = _detail(client.put(path, json={"due_at": None}, headers=ali))
    assert off.due_at is None and off.history[0].kind == "due_cleared"

    row = db.get(BoardCard, card.id)
    assert row is not None
    row.due_at = utcnow() - timedelta(minutes=5)
    db.commit()
    seen = _board(client, "sales", ali)
    assert seen.due.overdue == 1 and seen.due.today >= 0
    assert seen.columns[0].cards[0].overdue
    assert _board(client, "sales", ali, due="overdue").columns[0].total == 1
    assert _board(client, "sales", ali, due="set").columns[0].total == 1


def test_the_nearest_deadline_is_on_top_of_its_column(
    client: TestClient, db: Session
) -> None:
    _live(db)
    for name in ("a", "b", "c"):
        _client(db, f"{name}@shop.test")
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    ids = {}
    for _ in range(3):
        card = _detail(client.post(f"{URL}/sales/take", headers=ali))
        ids[card.client.email] = card.id
    client.put(
        f"{URL}/cards/{ids['b@shop.test']}/due", json={"due_at": _in(5)}, headers=ali
    )
    client.put(
        f"{URL}/cards/{ids['c@shop.test']}/due", json={"due_at": _in(1)}, headers=ali
    )

    lane = _board(client, "sales", ali).columns[0]
    assert [c.client.email for c in lane.cards][:2] == ["c@shop.test", "b@shop.test"]
    assert lane.cards[2].due_at is None


def test_missed_calls_are_counted_and_only_the_lead_gives_the_lead_back(
    client: TestClient, db: Session
) -> None:
    card, ali, _ = _taken(client, db)
    press = f"{URL}/cards/{card.id}/actions"
    client.post(press, json={"action": "no_contact"}, headers=ali)
    again = _detail(
        client.post(press, json={"action": "no_contact", "due_at": _in(2)}, headers=ali)
    )
    assert (
        again.attempts == 2
        and again.column == "no_contact"
        and again.due_at is not None
    )

    # The manager has no «Navbatga qaytarish» any more.
    refused = client.post(
        press, json={"action": "release", "note": "Ta'tilga chiqyapman"}, headers=ali
    )
    assert refused.status_code == 409
    give = f"{URL}/cards/{card.id}/assign"
    assert client.post(give, json={"staff_id": None}, headers=ali).status_code == 404

    boss = _staff(db, "boss@office.test", superuser=True)
    back = _detail(client.post(give, json={"staff_id": None}, headers=boss))
    assert back.column == "unworked" and back.manager is None and back.due_at is None
    assert back.history[0].kind == "returned"
    assert client.get(f"{URL}/cards/{card.id}", headers=ali).status_code == 404


def test_a_discount_card_given_back_stays_in_its_column_for_lid_olish(
    client: TestClient, db: Session
) -> None:
    card, ali, _ = _taken(client, db)
    press = f"{URL}/cards/{card.id}/actions"
    client.post(press, json={"action": "contacted"}, headers=ali)

    owner = _staff(db, "owner@office.test", Role.OWNER)
    back = _detail(
        client.post(
            f"{URL}/cards/{card.id}/assign", json={"staff_id": None}, headers=owner
        )
    )
    assert back.column == "discount_20" and back.manager is None
    assert back.history[0].kind == "returned"
    assert back.offer is not None and back.offer.percent == 20

    vali = _staff(db, "vali@office.test", Role.SALES)
    taken = _detail(client.post(f"{URL}/sales/take", headers=vali))
    assert taken.id == card.id and taken.column == "discount_20"
    assert taken.manager is not None and taken.history[0].kind == "taken"


def test_a_bill_moves_the_card_to_awaiting_and_back_when_unpaid(
    client: TestClient, db: Session
) -> None:
    card, ali, owner = _taken(client, db)
    press = f"{URL}/cards/{card.id}/actions"
    client.post(press, json={"action": "no_contact"}, headers=ali)
    bill = _bill(db, owner)

    _sweep(db)
    waiting = _detail(client.get(f"{URL}/cards/{card.id}", headers=ali))
    assert waiting.column == "awaiting" and waiting.has_bill
    assert waiting.bill is not None and waiting.bill.number == "TA-BILL"
    assert waiting.history[0].kind == "bill_opened"
    assert _sweep(db) == (0, 0)

    bill.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    _sweep(db)
    late = _detail(client.get(f"{URL}/cards/{card.id}", headers=ali))
    assert late.column == "callback" and late.overdue and not late.has_bill
    assert late.history[0].kind == "bill_unpaid"
    assert _sweep(db) == (0, 0)


def test_a_bill_leaves_a_discount_card_where_it_is(
    client: TestClient, db: Session
) -> None:
    card, ali, owner = _taken(client, db)
    press = f"{URL}/cards/{card.id}/actions"
    client.post(press, json={"action": "contacted"}, headers=ali)
    _bill(db, owner)

    _sweep(db)
    seen = _board(client, "sales", ali)
    lane = next(c for c in seen.columns if c.code == "discount_20")
    assert lane.total == 1 and lane.cards[0].has_bill
    assert lane.cards[0].offer is not None and lane.cards[0].offer.percent == 20


def test_a_payment_sells_a_discount_card_and_the_old_buttons_are_gone(
    client: TestClient, db: Session
) -> None:
    card, ali, owner = _taken(client, db)
    press = f"{URL}/cards/{card.id}/actions"
    client.post(press, json={"action": "contacted"}, headers=ali)
    for gone in ("will_pay", "offer"):
        refused = client.post(
            press, json={"action": gone, "due_at": _in(4)}, headers=ali
        )
        assert refused.status_code == 409, gone

    _paid(db, owner)
    _sweep(db)
    sold = _detail(client.get(f"{URL}/cards/{card.id}", headers=ali))
    assert sold.column == "sold" and sold.due_at is None
    assert sold.offer is not None and sold.offer.percent == 0


def test_the_lead_adds_a_client_by_hand(client: TestClient, db: Session) -> None:
    _live(db)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)
    ali = _staff(db, "ali@office.test", Role.SALES)
    old = _client(db, "old@shop.test", minutes_ago=60 * 24 * 30)
    payer = _client(db, "payer@shop.test")
    _paid(db, payer)
    path = f"{URL}/boards/sales/cards"

    assert (
        client.get(
            f"{URL}/boards/sales/clients", params={"q": "old@"}, headers=ali
        ).status_code
        == 404
    )
    assert (
        client.post(path, json={"user_id": str(old.id)}, headers=ali).status_code == 404
    )
    found = client.get(
        f"{URL}/boards/sales/clients", params={"q": "old@"}, headers=lead
    ).json()
    assert [c["email"] for c in found["clients"]] == ["old@shop.test"]
    assert found["clients"][0]["card"] is None

    added = _detail(
        client.post(
            path, json={"user_id": str(old.id), "note": "Instagramdan"}, headers=lead
        )
    )
    assert added.column == "unworked" and added.manager is None
    assert added.history[0].kind == "added" and added.history[0].actor is not None
    twice = client.post(path, json={"user_id": str(old.id)}, headers=lead)
    assert twice.status_code == 409 and twice.json()["code"] == "card_exists"
    paid = client.post(path, json={"user_id": str(payer.id)}, headers=lead)
    assert paid.status_code == 409 and paid.json()["code"] == "client_paid"
    staff_id = client.get(f"{URL}/me", headers=ali).json()["user"]["id"]
    nobody = client.post(path, json={"user_id": staff_id}, headers=lead)
    assert nobody.status_code == 422 and nobody.json()["code"] == "client_not_found"
    again = client.get(
        f"{URL}/boards/sales/clients", params={"q": "old@"}, headers=lead
    ).json()
    assert again["clients"][0]["card"]["column"] == "unworked"

    # A closed card comes back, to the manager named.
    press = f"{URL}/cards/{added.id}/actions"
    client.post(f"{URL}/sales/take", headers=ali)
    client.post(press, json={"action": "close", "reason": "expensive"}, headers=ali)
    back = _detail(
        client.post(
            path, json={"user_id": str(old.id), "staff_id": staff_id}, headers=lead
        )
    )
    assert back.id == added.id and back.column == "new_lead" and back.closed_at is None
    assert back.manager is not None and back.manager.email == "ali@office.test"


def test_a_ticket_is_opened_by_hand(client: TestClient, db: Session) -> None:
    _live(db)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    owner = _client(db, "shop@shop.test")
    path = f"{URL}/boards/support/cards"

    me = client.get(f"{URL}/me", headers=boss).json()["can"]
    assert me["add_ticket"] and me["add_lead"]
    assert me["take_ticket"]
    assert client.get(f"{URL}/me", headers=zarina).json()["can"] == me | {
        "take": False,
        "assign": False,
        "move": False,
        "add_lead": False,
        "columns": False,
        "staff": False,
        "telephony": False,
        "renewal_manager": False,
    }
    assert (
        client.post(
            path, json={"user_id": str(owner.id), "note": "x"}, headers=seller
        ).status_code
        == 404
    )
    blank = client.post(path, json={"user_id": str(owner.id)}, headers=boss)
    assert blank.status_code == 422 and blank.json()["code"] == "note_required"

    opened = _detail(
        client.post(
            path,
            json={"user_id": str(owner.id), "note": "Telefonda so'radi"},
            headers=boss,
        )
    )
    assert opened.board == "support" and opened.column == "new"
    assert [r.code for r in opened.ticket_reasons] == ["manual"]
    assert opened.reason_chips[0].label == "Qo'lda ochilgan"
    assert opened.history[0].actor is not None

    # A Support member's own goes to themselves, into Ishlanmoqda.
    more = _detail(
        client.post(
            path, json={"user_id": str(owner.id), "note": "Yana"}, headers=zarina
        )
    )
    assert more.id == opened.id and len(more.ticket_reasons) == 2
    assert more.column == "in_progress"
    assert more.manager is not None and more.manager.email == "zarina@office.test"
    assert _board(client, "support", zarina, reason="manual").columns[1].total == 1
    assert _board(client, "support", zarina, reason="setup").columns[1].total == 0
    # A client another member works is not theirs to open.
    olim = _staff(db, "olim@office.test", Role.SUPPORT)
    held = client.post(
        path, json={"user_id": str(owner.id), "note": "Men ham"}, headers=olim
    )
    assert held.status_code == 409 and held.json()["code"] == "ticket_held"


def test_a_ticket_waits_for_the_client_is_given_up_and_reopened(
    client: TestClient, db: Session
) -> None:
    _live(db)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    olim = _staff(db, "olim@office.test", Role.SUPPORT)
    owner = _client(db, "shop@shop.test")
    opened = _detail(
        client.post(
            f"{URL}/boards/support/cards",
            json={"user_id": str(owner.id), "note": "Yordam"},
            headers=zarina,
        )
    )
    press = f"{URL}/cards/{opened.id}/actions"
    assert opened.column == "in_progress"

    bare = client.post(press, json={"action": "wait"}, headers=zarina)
    assert bare.status_code == 422 and bare.json()["code"] == "due_required"
    waiting = _detail(
        client.post(press, json={"action": "wait", "due_at": _in(24)}, headers=zarina)
    )
    assert waiting.column == "waiting" and waiting.due_at is not None
    assert [a.value for a in waiting.actions] == ["start", "resolve", "release"]
    assert (
        next(a for a in waiting.actions if a.value == "release").label == "Voz kechish"
    )
    assert _board(client, "support", olim).columns[2].total == 0
    assert _board(client, "support", zarina).columns[2].total == 1
    assert (
        client.put(
            f"{URL}/cards/{opened.id}/due", json={"due_at": None}, headers=olim
        ).status_code
        == 404
    )

    # The client writes in the Yordam chat: the wait is over.
    assert triggers.sweep_support(db, now=utcnow()) == 0
    chat = SupportConversation(owner_id=owner.id)
    db.add(chat)
    db.flush()
    db.add(
        SupportMessage(
            owner_id=owner.id,
            conversation_id=chat.id,
            sender_id=owner.id,
            body="Qildim",
        )
    )
    db.commit()
    assert triggers.sweep_support(db, now=utcnow()) == 1
    answered = _detail(client.get(f"{URL}/cards/{opened.id}", headers=zarina))
    assert answered.column == "in_progress" and answered.due_at is None
    assert answered.history[0].kind == "client_replied"

    silent = client.post(press, json={"action": "resolve"}, headers=zarina)
    assert silent.status_code == 422 and silent.json()["code"] == "note_required"
    left = _detail(
        client.post(
            press, json={"action": "release", "note": "Smenam tugadi"}, headers=zarina
        )
    )
    assert left.column == "new" and left.manager is None

    # Given up, it is in the queue again and no longer its old person's.
    assert client.get(f"{URL}/cards/{opened.id}", headers=zarina).status_code == 404
    taken = _detail(client.post(f"{URL}/support/take", headers=olim))
    assert taken.id == opened.id and taken.history[0].kind == "ticket_taken"
    solved = _detail(
        client.post(press, json={"action": "resolve", "note": "Ulandi"}, headers=olim)
    )
    assert solved.column == "confirming" and solved.closed_at is None
    again = _detail(client.post(press, json={"action": "reopen"}, headers=olim))
    assert again.column == "in_progress" and again.closed_at is None
    assert again.manager is not None and again.manager.email == "olim@office.test"
    assert again.history[0].kind == "reopened" and again.history[0].actor is not None


def test_today_is_the_offices_day(db: Session) -> None:
    from app.modules.boards.view import today_bounds

    start, end = today_bounds(datetime.fromisoformat("2026-11-12T20:30:00+00:00"))
    # 01:30 on the 13th in Tashkent.
    assert start.isoformat() == "2026-11-13T00:00:00+05:00"
    assert end - start == timedelta(days=1)
    assert db.scalar(select(BoardCard.id).limit(1)) is None
