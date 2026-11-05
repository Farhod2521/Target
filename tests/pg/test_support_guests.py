"""The sign-in page's chat against PostgreSQL: a guest starts it, the office
answers, and signing in moves it into the account named - and only that one."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.notifications.models import StaffChat
from app.modules.notifications.services import forward_guest_question
from app.modules.supportchat.models import (
    SupportConversation,
    SupportGuestChat,
    SupportGuestMessage,
    SupportMessage,
)
from tests.pg.test_office_actions import _staff
from tests.pg.test_office_telegram import FakeBot
from tests.pg.test_office_telegram import fake as fake  # the fixture
from tests.pg.test_supportchat import _auth, _user

URL = "/api/v1/support/guest"
OFFICE = "/api/v1/office/support/guests"
GUEST = {"name": "Ali Valiyev", "phone": "+998 90 123 45 67", "email": "Ali@Gmail.com"}


def _start(client: TestClient, address: str = "10.0.0.1", **extra: str) -> object:
    return client.post(
        URL, json={**GUEST, **extra}, headers={"X-Forwarded-For": address}
    )


def _as(token: str) -> dict[str, str]:
    return {"X-Guest-Token": token}


def test_a_guest_writes_and_the_office_answers(
    client: TestClient, db: Session, queued: list
) -> None:
    refused = _start(client, name=" ", phone="12", email="nope")
    assert refused.status_code == 422
    assert set(refused.json()["problems"]) == {"name", "phone", "email"}
    assert db.scalar(select(SupportGuestChat)) is None

    started = _start(client)
    assert started.status_code == 201, started.text
    token = started.json()["token"]
    chat = started.json()["chat"]
    assert chat["phone"] == "+998901234567" and chat["email"] == "ali@gmail.com"
    assert [m["body"] for m in chat["messages"]] == ["Parolni tiklash kerak."]
    assert chat["messages"][0]["own"] and chat["messages"][0]["who"] == "Siz"
    stored = db.scalar(select(SupportGuestChat))
    assert stored is not None and stored.token_hash != token
    assert [name for name, _ in queued] == [
        "app.modules.notifications.tasks.deliver_guest_question_task"
    ]

    assert client.get(URL, headers=_as("wrong")).status_code == 404
    said = client.post(
        f"{URL}/messages", json={"body": "Email: ali@gmail.com"}, headers=_as(token)
    )
    assert said.status_code == 201 and said.json()["side"] == "client"
    empty = client.post(f"{URL}/messages", json={"body": "  "}, headers=_as(token))
    assert empty.json()["code"] == "empty_message"

    member, office = _staff(db, Role.SUPPORT, email="support@office.test")
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    _user(db, "Ali@gmail.com", phone="+998901234567")
    assert client.get(OFFICE, headers=finance).status_code == 404
    assert (
        client.get("/api/v1/office/me", headers=office).json()["waiting"]["support"]
        == 1
    )

    queue = client.get(OFFICE, headers=office).json()
    assert [row["name"] for row in queue["rows"]] == ["Ali Valiyev"]
    assert (
        queue["rows"][0]["waiting"]
        and queue["rows"][0]["preview"] == "Email: ali@gmail.com"
    )
    chat_id = queue["rows"][0]["id"]

    thread = client.get(f"{OFFICE}/{chat_id}", headers=office).json()
    assert thread["account"]["email"] == "Ali@gmail.com"
    assert thread["account"]["phone_matches"] is True
    assert thread["messages"][0]["who"] == "Ali Valiyev"
    reply = client.post(
        f"{OFFICE}/{chat_id}/messages",
        json={"body": "Yangi parol: 12345678"},
        headers=office,
    )
    assert reply.status_code == 201 and reply.json()["who"] == member.full_name

    seen = client.get(URL, headers=_as(token)).json()
    assert seen["messages"][-1]["who"] == "Qo'llab-quvvatlash"
    assert seen["messages"][-1]["own"] is False
    assert seen["messages"][1]["read"] is True
    assert client.get(OFFICE, headers=office).json()["rows"] == []
    assert len(client.get(f"{OFFICE}?state=all", headers=office).json()["rows"]) == 1

    client.post(f"{URL}/messages", json={"body": "Rahmat"}, headers=_as(token))
    assert len(client.get(OFFICE, headers=office).json()["rows"]) == 1
    assert client.post(f"{OFFICE}/{chat_id}/settle", headers=office).status_code == 200
    assert client.get(OFFICE, headers=office).json()["rows"] == []


def test_signing_in_moves_the_words_only_into_the_account_named(
    client: TestClient, db: Session
) -> None:
    token = _start(client).json()["token"]
    _, office = _staff(db, Role.SUPPORT, email="support@office.test")
    chat_id = client.get(OFFICE, headers=office).json()["rows"][0]["id"]
    client.post(
        f"{OFFICE}/{chat_id}/messages", json={"body": "Parol: abc"}, headers=office
    )

    stranger = _user(db, "boshqa@example.com", phone="+998935554433")
    claimed = client.post(f"{URL}/claim", headers={**_auth(stranger), **_as(token)})
    assert claimed.json() == {"moved": 0}
    assert db.scalar(select(SupportConversation)) is None

    # Named by the phone alone: the guest wrote another email.
    owner = _user(db, "ali.boshqa@example.com", phone="+998901234567")
    old = client.post(
        "/api/v1/support/messages", headers=_auth(owner), data={"body": "Eski savol"}
    )
    assert old.status_code == 201
    claimed = client.post(f"{URL}/claim", headers={**_auth(owner), **_as(token)})
    assert claimed.json() == {"moved": 2}
    again = client.post(f"{URL}/claim", headers={**_auth(owner), **_as(token)})
    assert again.json() == {"moved": 0}

    screen = client.get("/api/v1/support", headers=_auth(owner)).json()
    assert [(m["body"], m["side"]) for m in screen["messages"]] == [
        ("Parolni tiklash kerak.", "client"),
        ("Parol: abc", "office"),
        ("Eski savol", "client"),
    ]
    conversation = db.scalar(select(SupportConversation))
    db.refresh(conversation)
    assert conversation is not None and conversation.last_office_at is not None
    assert len(db.scalars(select(SupportMessage)).all()) == 3

    moved = client.get(URL, headers=_as(token)).json()
    assert moved["moved"] is True
    refused = client.post(f"{URL}/messages", json={"body": "yana"}, headers=_as(token))
    assert refused.status_code == 409 and refused.json()["code"] == "guest_chat_moved"
    office_refused = client.post(
        f"{OFFICE}/{chat_id}/messages", json={"body": "yana"}, headers=office
    )
    assert office_refused.status_code == 409
    thread = client.get(f"{OFFICE}/{chat_id}", headers=office).json()
    assert thread["moved"] is True and thread["claimed_by"]["email"] == owner.email
    assert client.get(OFFICE, headers=office).json()["rows"] == []
    assert client.post(f"{URL}/claim", headers=_as(token)).status_code == 401


def test_one_address_starts_only_a_few_chats(client: TestClient, db: Session) -> None:
    for _ in range(5):
        assert _start(client, address="10.9.9.9").status_code == 201
    too_many = _start(client, address="10.9.9.9")
    assert too_many.status_code == 429
    assert too_many.json()["code"] == "too_many_guest_chats"
    assert _start(client, address="10.9.9.10").status_code == 201


def test_the_office_hears_of_a_guest_in_the_staff_bot(
    client: TestClient, db: Session, fake: FakeBot
) -> None:
    member, _ = _staff(db, Role.SUPPORT, email="support@office.test")
    seller, _ = _staff(db, Role.SALES, email="sales@office.test")
    for who, chat_id in ((member, "501"), (seller, "502")):
        db.add(
            StaffChat(
                owner_id=who.id, chat_id=chat_id, is_active=True, linked_at=utcnow()
            )
        )
    db.commit()
    _start(client, body="Parolim esimda yo'q")
    message = db.scalar(select(SupportGuestMessage))
    assert message is not None

    assert forward_guest_question(db, message_id=str(message.id)) == 1
    [(name, fields)] = fake.calls
    assert name == "send_message" and fields["chat_id"] == "501"
    assert "Ali Valiyev · +998901234567 · ali@gmail.com" in fields["text"]
    assert "Parolim esimda yo'q" in fields["text"]
    assert f"/ofis/chat/mehmon/{message.chat_id}/" in fields["text"]
    assert forward_guest_question(db, message_id="not-a-uuid") == 0
