"""Support's board after the rework: a member reads only their own tickets
and takes them one a press, five in Ishlanmoqda at most; a wait ends with
its timer; the client closes the ticket by saying it is solved; a ticket
goes to a developer; Sales' words come with its ticket; a plan the office
gave counts as one bought."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import SentMessage

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import InvoiceKind, SubscriptionStatus
from app.modules.billing.models import Subscription
from app.modules.boards import confirm, triggers
from app.modules.boards.constants import TICKET_TAKE_LIMIT, TicketReason
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.schemas import BoardViewOut, CardDetailOut
from app.modules.boards.tickets import raise_ticket
from app.modules.notifications.models import SupportBotChat
from app.modules.notifications.services import support_bot as support_bot_module
from app.modules.notifications.services.support_bot import handle_support_update
from tests.pg.test_boards_me import _auth, _staff
from tests.pg.test_boards_sales import _client, _paid, _plan
from tests.pg.test_boards_support import _live, _ticket

URL = "/api/v2/office"
MINE = "/api/v2/support-ticket"


def _detail(answer: Any) -> CardDetailOut:
    assert answer.status_code in (200, 201), answer.text
    return CardDetailOut.model_validate(answer.json())


def _board(client: TestClient, head: dict[str, str]) -> BoardViewOut:
    answer = client.get(f"{URL}/boards/support", headers=head)
    assert answer.status_code == 200, answer.text
    return BoardViewOut.model_validate(answer.json())


def _raised(db: Session, email: str, *, minutes_ago: int = 0) -> User:
    owner = _client(db, email)
    raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.SETUP,
        ref="a",
        now=utcnow() - timedelta(minutes=minutes_ago),
    )
    db.commit()
    return owner


def _in(hours: float) -> str:
    return (utcnow() + timedelta(hours=hours)).isoformat()


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def send_message(self, **fields: Any) -> SentMessage:
        self.calls.append(("send_message", fields))
        return SentMessage(message_id=7, chat_id=fields.get("chat_id", ""))

    def edit_message_text(self, **fields: Any) -> None:
        self.calls.append(("edit_message_text", fields))

    def answer_callback_query(self, **fields: Any) -> None:
        self.calls.append(("answer_callback_query", fields))

    def named(self, name: str) -> list[dict[str, Any]]:
        return [fields for called, fields in self.calls if called == name]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    monkeypatch.setattr(confirm, "support_bot", opened)
    monkeypatch.setattr(support_bot_module, "support_bot", opened)
    monkeypatch.setattr(settings, "support_bot_token", "t")
    monkeypatch.setattr(settings, "support_bot_webhook_secret", "s")
    monkeypatch.setattr(settings, "support_bot_username", "yordam_bot")
    return client


def _pressed(chat_id: int, data: str) -> dict[str, Any]:
    sender = {"id": chat_id, "is_bot": False, "first_name": "Mijoz"}
    return {
        "update_id": 1,
        "callback_query": {
            "id": "q1",
            "from": sender,
            "data": data,
            "message": {
                "message_id": 7,
                "chat": {"id": chat_id, "type": "private"},
                "date": 0,
            },
        },
    }


def test_a_member_takes_one_ticket_a_press_and_five_at_most(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owners = [
        _raised(db, f"shop{n}@shop.test", minutes_ago=60 - n)
        for n in range(TICKET_TAKE_LIMIT + 1)
    ]
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    olim = _staff(db, "olim@office.test", Role.SUPPORT)
    take = f"{URL}/support/take"

    before = _board(client, zarina)
    assert before.take is not None
    assert (before.take.queue, before.take.working, before.take.limit) == (6, 0, 5)
    assert sum(c.total for c in before.columns) == 0

    taken = [_detail(client.post(take, headers=zarina)) for _ in range(5)]
    # The one that waited longest comes first.
    assert [t.client.email for t in taken] == [o.email for o in owners[:5]]
    assert all(t.column == "in_progress" for t in taken)
    full = client.post(take, headers=zarina)
    assert full.status_code == 409 and full.json()["code"] == "take_limit"
    mine = _board(client, zarina)
    assert mine.take is not None and (mine.take.queue, mine.take.working) == (1, 5)
    assert mine.columns[1].total == 5 and _board(client, olim).columns[1].total == 0

    # A ticket waiting for its client is not counted: there is room again.
    press = f"{URL}/cards/{taken[0].id}/actions"
    client.post(press, json={"action": "wait", "due_at": _in(2)}, headers=zarina)
    sixth = _detail(client.post(take, headers=zarina))
    assert sixth.client.email == owners[5].email
    empty = client.post(take, headers=olim)
    assert empty.status_code == 409 and empty.json()["code"] == "no_ticket_to_take"

    # The waiting one comes back by hand over the limit: it is theirs already.
    back = _detail(client.post(press, json={"action": "start"}, headers=zarina))
    assert back.column == "in_progress"
    assert _board(client, zarina).columns[1].total == 6


def test_the_owner_sees_every_ticket_and_gives_one_with_a_note(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "shop@shop.test")
    boss = _staff(db, "boss@office.test", Role.OWNER)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    seller = _staff(db, "ali@office.test", Role.SALES)
    people = client.get(f"{URL}/boards/support/staff", headers=boss).json()["staff"]
    assert [p["email"] for p in people] == ["zarina@office.test"]
    seller_id = db.scalar(select(User.id).where(User.email == "ali@office.test"))
    path = f"{URL}/boards/support/cards"
    assert seller

    wrong = client.post(
        path,
        json={"user_id": str(owner.id), "note": "x", "staff_id": str(seller_id)},
        headers=boss,
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "not_on_board"
    opened = _detail(
        client.post(
            path,
            json={
                "user_id": str(owner.id),
                "note": "Piksel ulanmayapti",
                "staff_id": people[0]["id"],
            },
            headers=boss,
        )
    )
    assert opened.column == "new"
    assert opened.manager is not None and opened.manager.email == "zarina@office.test"
    assert opened.ticket_reasons[0].detail == "Piksel ulanmayapti"
    assert {h.kind for h in opened.history} == {"ticket", "assigned"}

    # Its person reads it in Yangi and starts it; the Owner reads all.
    assert _board(client, zarina).columns[0].total == 1
    assert _board(client, boss).columns[0].total == 1
    started = _detail(
        client.post(
            f"{URL}/cards/{opened.id}/actions", json={"action": "start"}, headers=zarina
        )
    )
    assert started.column == "in_progress"


def test_a_wait_ends_with_its_timer(client: TestClient, db: Session) -> None:
    _live(db)
    _raised(db, "shop@shop.test")
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    press = f"{URL}/cards/{taken.id}/actions"
    client.post(press, json={"action": "wait", "due_at": _in(2)}, headers=zarina)

    assert triggers.wait_over(db, now=utcnow() + timedelta(hours=1)) == 0
    assert triggers.wait_over(db, now=utcnow() + timedelta(hours=3)) == 1
    back = _detail(client.get(f"{URL}/cards/{taken.id}", headers=zarina))
    assert back.column == "in_progress" and back.due_at is None
    assert back.history[0].kind == "wait_over"
    assert back.manager is not None


def test_a_ticket_goes_to_a_developer_and_comes_back(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _raised(db, "shop@shop.test")
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    press = f"{URL}/cards/{taken.id}/actions"

    bare = client.post(press, json={"action": "to_developer"}, headers=zarina)
    assert bare.status_code == 422 and bare.json()["code"] == "note_required"
    given = _detail(
        client.post(
            press,
            json={"action": "to_developer", "note": "Lid forma ochilmaydi"},
            headers=zarina,
        )
    )
    assert given.column == "developer" and given.history[0].kind == "developer"
    assert [a.value for a in given.actions] == ["start", "resolve"]
    # Not counted against the limit, and still its person's.
    assert _board(client, zarina).take.working == 0  # type: ignore[union-attr]
    back = _detail(client.post(press, json={"action": "start"}, headers=zarina))
    assert back.column == "in_progress"


def test_the_client_closes_the_ticket_on_the_site(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _raised(db, "shop@shop.test")
    me = _auth(owner)
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    press = f"{URL}/cards/{taken.id}/actions"
    resolve = {"action": "resolve", "note": "Ulandi"}

    assert client.get(MINE, headers=me).json() == {"question": None}
    early = client.post(f"{MINE}/answer", json={"solved": True}, headers=me)
    assert early.json() == {"result": "stale"}
    client.post(press, json=resolve, headers=zarina)
    # Asked once, however often the sweep runs; no Telegram: the site only.
    assert confirm.ask_clients(db, now=utcnow()) == 1
    assert confirm.ask_clients(db, now=utcnow()) == 0
    asked = _detail(client.get(f"{URL}/cards/{taken.id}", headers=zarina))
    assert asked.history[0].kind == "asked"
    assert "saytda" in asked.history[0].body
    assert client.get(MINE, headers=me).json()["question"] is not None

    no = client.post(f"{MINE}/answer", json={"solved": False}, headers=me)
    assert no.json() == {"result": "reopened"}
    back = _detail(client.get(f"{URL}/cards/{taken.id}", headers=zarina))
    assert back.column == "in_progress" and back.history[0].kind == "denied"
    assert back.manager is not None and back.manager.email == "zarina@office.test"
    assert client.get(MINE, headers=me).json() == {"question": None}

    client.post(press, json=resolve, headers=zarina)
    yes = client.post(f"{MINE}/answer", json={"solved": True}, headers=me)
    assert yes.json() == {"result": "solved"}
    done = _detail(client.get(f"{URL}/cards/{taken.id}", headers=zarina))
    assert done.column == "resolved" and done.closed_at is not None
    assert done.history[0].kind == "confirmed" and done.history[0].body == "Saytda"
    again = client.post(f"{MINE}/answer", json={"solved": False}, headers=me)
    assert again.json() == {"result": "stale"}


def test_silence_closes_the_ticket_after_a_day(client: TestClient, db: Session) -> None:
    _live(db)
    _raised(db, "shop@shop.test")
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    client.post(
        f"{URL}/cards/{taken.id}/actions",
        json={"action": "resolve", "note": "Ulandi"},
        headers=zarina,
    )

    assert confirm.close_unanswered(db, now=utcnow() + timedelta(hours=23)) == 0
    assert confirm.close_unanswered(db, now=utcnow() + timedelta(hours=25)) == 1
    closed = _detail(client.get(f"{URL}/cards/{taken.id}", headers=zarina))
    assert closed.column == "closed" and closed.closed_at is not None
    assert closed.history[0].kind == "unanswered"
    assert [a.value for a in closed.actions] == ["reopen"]


def test_the_client_answers_in_the_support_bot(
    client: TestClient, db: Session, fake: FakeBot
) -> None:
    _live(db)
    owner = _raised(db, "shop@shop.test")
    other = _client(db, "other@shop.test")
    db.add_all(
        [
            SupportBotChat(chat_id="555", owner_id=owner.id, is_active=True),
            SupportBotChat(chat_id="777", owner_id=other.id, is_active=True),
        ]
    )
    db.commit()
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    client.post(
        f"{URL}/cards/{taken.id}/actions",
        json={"action": "resolve", "note": "Ulandi"},
        headers=zarina,
    )

    assert triggers.sweep_support(db, now=utcnow()) == 1
    sent = fake.named("send_message")
    assert len(sent) == 1 and sent[0]["chat_id"] == "555"
    assert "hal bo'ldimi" in sent[0]["text"]
    yes, no = (button.data for button in sent[0]["buttons"])

    # A forwarded question keeps its buttons; a stranger's press is nothing.
    assert handle_support_update(db, payload=_pressed(777, yes), now=utcnow()) == (
        "ticket_stranger"
    )
    ticket = _ticket(db, owner)
    assert ticket is not None and ticket.column_code == "confirming"

    assert handle_support_update(db, payload=_pressed(555, no), now=utcnow()) == (
        "ticket_reopened"
    )
    ticket = _ticket(db, owner)
    assert ticket is not None and ticket.column_code == "in_progress"
    assert "qayta ochildi" in fake.named("edit_message_text")[-1]["text"]
    # The same question's other button no longer answers anything.
    assert handle_support_update(db, payload=_pressed(555, yes), now=utcnow()) == (
        "ticket_stale"
    )
    line = db.scalar(select(BoardCardEvent).where(BoardCardEvent.kind == "denied"))
    assert line is not None and line.body == "Support botda"


def test_sales_words_come_with_the_ticket(client: TestClient, db: Session) -> None:
    _live(db)
    owner = _client(db, "lead@shop.test")
    triggers.sweep_sales(db, now=utcnow())
    ali = _staff(db, "ali@office.test", Role.SALES)
    lead = _detail(client.post(f"{URL}/sales/take", headers=ali))
    press = f"{URL}/cards/{lead.id}/actions"
    client.post(press, json={"action": "contacted"}, headers=ali)
    client.post(
        f"{URL}/cards/{lead.id}/notes",
        json={"body": "Instagram sahifasi yo'q, ochib berish kerak"},
        headers=ali,
    )
    client.post(
        press,
        json={"action": "needs_support", "on": True, "note": "Pixel kerak"},
        headers=ali,
    )
    _paid(db, owner)
    triggers.sweep_sales(db, now=utcnow())
    triggers.sweep_support(db, now=utcnow())

    ticket = _ticket(db, owner)
    assert ticket is not None
    detail = str(ticket.reasons[0]["detail"])
    assert "ali@office.test" in detail
    assert "Instagram sahifasi yo'q" in detail
    assert "Pixel kerak" in detail


def test_a_plan_the_office_gave_sells_the_lead_and_is_watched_for_setup(
    db: Session,
) -> None:
    _live(db)
    owner = _client(db, "gift@shop.test")
    topped = _client(db, "wallet@shop.test")
    boss = User(email="b@office.test", password="!", is_staff=True, is_superuser=True)
    db.add(boss)
    db.flush()
    # Money paid for something that is not a plan leaves a sign-up a lead.
    seats = _paid(db, topped)
    seats.kind = str(InvoiceKind.SEATS)
    db.commit()
    triggers.sweep_sales(db, now=utcnow())
    cards = {
        card.owner_id: card
        for card in db.scalars(select(BoardCard).where(BoardCard.board == "sales"))
    }
    assert cards[topped.id].column_code == "unworked"
    assert cards[owner.id].column_code == "unworked"

    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=_plan(db).id,
            status=SubscriptionStatus.ACTIVE,
            extra_pages=0,
            started_at=utcnow() - timedelta(minutes=61),
            expires_at=utcnow() + timedelta(days=30),
            activated_by_id=boss.id,
            note="",
        )
    )
    db.commit()
    triggers.sweep_sales(db, now=utcnow())
    triggers.sweep_sales(db, now=utcnow())
    db.expire_all()
    sold = db.scalar(
        select(BoardCard).where(
            BoardCard.board == "sales", BoardCard.owner_id == owner.id
        )
    )
    assert sold is not None and sold.column_code == "sold"
    line = db.scalar(select(BoardCardEvent).where(BoardCardEvent.ref == "sold"))
    assert line is not None and "ofisdan" in line.body

    assert triggers.setup_late(db, now=utcnow()) == 1
    assert triggers.setup_late(db, now=utcnow()) == 0
    ticket = _ticket(db, owner)
    assert ticket is not None and ticket.reasons[0]["code"] == "setup"


def test_a_ticket_solved_while_the_sweep_ran_is_asked_once(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _raised(db, "shop@shop.test")
    zarina = _staff(db, "zarina@office.test", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    client.post(
        f"{URL}/cards/{taken.id}/actions",
        json={"action": "resolve", "note": "Ulandi"},
        headers=zarina,
    )

    # The run's clock is a moment behind the press.
    assert confirm.ask_clients(db, now=utcnow() - timedelta(seconds=30)) == 1
    assert confirm.ask_clients(db, now=utcnow()) == 0
