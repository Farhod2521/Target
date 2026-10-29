"""The office's side of the support chat: the queue, a thread, the writes,
the journalled readings and the office socket."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.common.config import settings
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.supportchat.models import SupportConversation
from tests.pg.test_office_actions import _staff
from tests.pg.test_supportchat import PNG, _send, _token, _user

URL = "/api/v1/office/support"


@pytest.fixture(autouse=True)
def media_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return tmp_path


def _journal(db: Session) -> list[str]:
    return list(db.scalars(select(StaffAction.kind).order_by(StaffAction.created_at)))


def test_the_queue_a_thread_a_reply_and_settling(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "mijoz@example.com")
    quiet = _user(db, "jim@example.com")
    member, office = _staff(db, Role.SUPPORT, email="support@office.test")
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    _send(client, owner, body="Reklama to'xtadi")
    _send(client, quiet, body="Rahmat")

    assert client.get(URL, headers=finance).status_code == 404
    queue = client.get(URL, headers=office).json()
    assert queue["total"] == 2
    assert [row["customer"]["email"] for row in queue["rows"]] == [
        "mijoz@example.com",
        "jim@example.com",
    ]
    assert queue["rows"][0]["preview"] == "Reklama to'xtadi"
    chat_id = queue["rows"][0]["id"]

    thread = client.get(f"{URL}/{chat_id}", headers=office).json()
    assert thread["messages"][0]["who"] == "mijoz"
    assert thread["ws_path"] == f"/api/v1/office/support/{chat_id}/ws"
    chat = db.get(SupportConversation, chat_id)
    db.refresh(chat)
    assert chat is not None and chat.office_read_at is not None

    sent = client.post(
        f"{URL}/{chat_id}/messages",
        headers=office,
        data={"body": "Tekshiramiz", "send_key": "k1"},
        files={"attachments": ("chek.png", PNG, "image/png")},
    )
    assert sent.status_code == 201, sent.text
    reply = sent.json()["message"]
    assert reply["own"] and reply["who"] == "support@office.test"
    door = reply["files"][0]["url"]
    assert door.startswith("/api/v1/office/support/files/")
    again = client.post(
        f"{URL}/{chat_id}/messages",
        headers=office,
        data={"body": "Tekshiramiz", "send_key": "k1"},
    )
    assert again.json() == {"already_sent": True, "message": None}
    assert client.get(door, headers=office).status_code == 200
    assert client.get(f"{door}?token={_token(member)}").status_code == 200
    assert client.get(door, headers=finance).status_code == 404

    edited = client.patch(
        f"{URL}/messages/{reply['id']}", headers=office, json={"body": "Tekshirdik"}
    )
    assert edited.json()["body"] == "Tekshirdik"

    quiet_chat = queue["rows"][1]["id"]
    assert client.post(f"{URL}/{quiet_chat}/settle", headers=office).status_code == 200
    waiting = client.get(URL, headers=office).json()
    assert waiting["total"] == 0, "answered and settled chats leave the queue"
    assert client.get(URL, headers=office, params={"state": "all"}).json()["total"] == 2
    assert _journal(db) == [
        ActionKind.SUPPORT_VIEW,
        ActionKind.SUPPORT_FILE,
    ], "the second file reading falls inside the quiet window"


def test_the_office_writes_first_to_a_client_without_a_chat(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "yangi@example.com")
    _, office = _staff(db, Role.OWNER, email="owner@office.test")
    empty = client.get(f"{URL}/customers/{owner.id}", headers=office).json()
    assert empty["conversation_id"] is None and empty["messages"] == []

    first = client.post(
        f"{URL}/customers/{owner.id}/messages", headers=office, data={"body": "Salom"}
    )
    assert first.status_code == 201, first.text
    opened = client.get(f"{URL}/customers/{owner.id}", headers=office).json()
    assert opened["conversation_id"] is not None
    assert [row["body"] for row in opened["messages"]] == ["Salom"]


def test_the_office_socket_speaks_for_the_office(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "mijoz@example.com")
    member, _ = _staff(db, Role.SUPPORT, email="support@office.test")
    _send(client, owner, body="Savol")
    chat = db.scalar(select(SupportConversation))
    assert chat is not None

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"{URL}/{chat.id}/ws?token={_token(owner)}") as door,
    ):
        door.receive_json()

    with (
        client.websocket_connect(
            f"/api/v1/support/ws?token={_token(owner)}"
        ) as client_side,
        client.websocket_connect(
            f"{URL}/{chat.id}/ws?token={_token(member)}"
        ) as office_side,
    ):
        assert client_side.receive_json()["type"] == "read"
        office_side.send_json({"typing": True})
        assert client_side.receive_json() == {"type": "typing", "side": "office"}
        office_side.send_json({"body": "Javob", "nonce": "o1"})
        mine = office_side.receive_json()
        assert mine["nonce"] == "o1" and mine["message"]["own"]
        theirs = client_side.receive_json()
        assert theirs["message"]["who"] == "Qo'llab-quvvatlash"
        assert not theirs["message"]["own"]
