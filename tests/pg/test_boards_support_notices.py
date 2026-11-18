"""The ticket's person told in the staff bot: given the ticket, the wait
over, the client writing back or saying no, a new problem; never of their
own doing, never twice, never for a ticket with nobody on it. The client's
chat message goes to the ticket's person alone."""

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
from app.modules.boards import confirm, notices, triggers
from app.modules.boards.constants import TicketReason
from app.modules.boards.models import BoardCardEvent
from app.modules.boards.tickets import raise_ticket
from app.modules.notifications import bot as bot_module
from app.modules.notifications.models import StaffChat
from app.modules.notifications.services import forward_support_question
from app.modules.notifications.services import support_desk as desk_module
from app.modules.supportchat.models import SupportMessage
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import URL, _detail, _live, _ticket
from tests.pg.test_supportchat import _send


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_message(self, **fields: Any) -> SentMessage:
        self.calls.append(fields)
        return SentMessage(
            message_id=len(self.calls), chat_id=fields.get("chat_id", "")
        )

    def to(self, chat_id: str) -> list[str]:
        return [c["text"] for c in self.calls if c["chat_id"] == chat_id]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    monkeypatch.setattr(bot_module, "staff_bot", opened)
    monkeypatch.setattr(desk_module, "staff_bot", opened)
    monkeypatch.setattr(settings, "staff_bot_token", "t")
    monkeypatch.setattr(settings, "staff_bot_webhook_secret", "s")
    monkeypatch.setattr(settings, "staff_bot_username", "office_bot")
    return client


def _linked(db: Session, email: str, chat_id: str) -> User:
    member = db.scalar(select(User).where(User.email == email))
    assert member is not None
    db.add(
        StaffChat(
            owner_id=member.id, chat_id=chat_id, is_active=True, linked_at=utcnow()
        )
    )
    db.commit()
    return member


def _raise(db: Session, owner: User, reason: TicketReason, ref: str) -> None:
    raise_ticket(
        db,
        owner_id=owner.id,
        reason=reason,
        ref=ref,
        now=utcnow(),
        detail=f"{reason} keldi",
    )
    db.commit()


def test_the_person_hears_what_comes_back_to_them(
    client: TestClient, db: Session, fake: FakeBot
) -> None:
    _live(db)
    zarina = _staff(db, "zarina@ntc.test", Role.SUPPORT)
    _linked(db, "zarina@ntc.test", "701")
    owner = _client(db, "shop@ntc.test")
    _raise(db, owner, TicketReason.SETUP, "a")
    # Nobody holds it yet: nothing to tell.
    assert notices.tell_ticket_people(db, now=utcnow()) == 0

    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    # Her own take is not news to her.
    assert notices.tell_ticket_people(db, now=utcnow()) == 0

    # She waits for the client; the time runs out, and a new problem comes.
    wait = client.post(
        f"{URL}/cards/{taken.id}/actions",
        headers=zarina,
        json={"action": "wait", "due_at": (utcnow() + timedelta(hours=1)).isoformat()},
    )
    assert wait.status_code == 200, wait.text
    triggers.wait_over(db, now=utcnow() + timedelta(hours=2))
    _raise(db, owner, TicketReason.META_ERROR, "b")
    assert notices.tell_ticket_people(db, now=utcnow()) == 1
    [text] = fake.to("701")
    assert "Kutish vaqti tugadi" in text and "Yangi muammo" in text
    assert "Shop" in text and f"karta={taken.id}" in text
    # Told once.
    assert notices.tell_ticket_people(db, now=utcnow()) == 0

    # She calls it solved; the client says no: back to her.
    client.post(
        f"{URL}/cards/{taken.id}/actions",
        headers=zarina,
        json={"action": "resolve", "note": "Tayyor"},
    )
    confirm.answer(db, owner_id=owner.id, solved=False, via="test", now=utcnow())
    assert notices.tell_ticket_people(db, now=utcnow()) == 1
    assert "hal bo'lmadi" in fake.to("701")[-1]


def test_the_owner_giving_a_ticket_tells_its_new_person(
    client: TestClient, db: Session, fake: FakeBot
) -> None:
    _live(db)
    boss = _staff(db, "boss@ntc.test", Role.OWNER)
    _staff(db, "olim@ntc.test", Role.SUPPORT)
    olim = _linked(db, "olim@ntc.test", "702")
    owner = _client(db, "given@ntc.test")
    _raise(db, owner, TicketReason.AI, "a")
    ticket = _ticket(db, owner)
    assert ticket is not None
    given = client.post(
        f"{URL}/cards/{ticket.id}/assign", headers=boss, json={"staff_id": str(olim.id)}
    )
    assert given.status_code == 200, given.text
    assert notices.tell_ticket_people(db, now=utcnow()) == 1
    assert "Zayavka sizga berildi (boss@ntc.test)" in fake.to("702")[0]


def test_an_old_line_is_not_news(
    client: TestClient, db: Session, fake: FakeBot
) -> None:
    _live(db)
    zarina = _staff(db, "zarina3@ntc.test", Role.SUPPORT)
    _linked(db, "zarina3@ntc.test", "703")
    owner = _client(db, "old@ntc.test")
    _raise(db, owner, TicketReason.SETUP, "a")
    _detail(client.post(f"{URL}/support/take", headers=zarina))
    _raise(db, owner, TicketReason.META_ERROR, "b")
    assert notices.tell_ticket_people(db, now=utcnow() + timedelta(hours=2)) == 0
    assert fake.calls == []
    line = db.scalar(select(BoardCardEvent).where(BoardCardEvent.kind == "reason"))
    assert line is not None and line.noticed_at is None


def test_the_clients_message_goes_to_the_ticket_person_alone(
    client: TestClient, db: Session, fake: FakeBot, queued: list
) -> None:
    _live(db)
    zarina = _staff(db, "zarina4@ntc.test", Role.SUPPORT)
    _staff(db, "olim4@ntc.test", Role.SUPPORT)
    _linked(db, "zarina4@ntc.test", "704")
    _linked(db, "olim4@ntc.test", "705")
    owner = _client(db, "chat@ntc.test")

    # No ticket: everybody in Support gets the copy.
    _send(client, owner, body="Salom")
    first = db.scalars(
        select(SupportMessage).order_by(SupportMessage.created_at)
    ).all()[-1]
    assert forward_support_question(db, message_id=str(first.id), now=utcnow()) == 2

    # Zarina holds the ticket: only she does.
    _raise(db, owner, TicketReason.SETUP, "a")
    _detail(client.post(f"{URL}/support/take", headers=zarina))
    _send(client, owner, body="Reklama to'xtadi")
    second = db.scalars(
        select(SupportMessage).order_by(SupportMessage.created_at)
    ).all()[-1]
    fake.calls.clear()
    assert forward_support_question(db, message_id=str(second.id), now=utcnow()) == 1
    assert [c["chat_id"] for c in fake.calls] == ["704"]
