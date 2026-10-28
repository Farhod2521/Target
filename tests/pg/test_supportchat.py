"""The client's support chat against PostgreSQL: sending with files, the
edit and delete window, read marks, other people's rows, the poll and the
socket."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.common import hooks, tokens
from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.models import ActionLog
from app.modules.supportchat import live
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.models import (
    SupportAttachment,
    SupportConversation,
    SupportMessage,
)
from app.modules.supportchat.services import (
    QUESTION_POSTED,
    REPLY_POSTED,
    write_to_client,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def media_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return tmp_path


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, dict]]]:
    """Hooks fired, heard by a listener the test puts on and takes off."""
    seen: list[tuple[str, dict]] = []
    handlers = dict(hooks._handlers)
    for name in (QUESTION_POSTED, REPLY_POSTED):
        hooks.on(name)(lambda name=name, **kw: seen.append((name, kw)))
    yield seen
    hooks._handlers.clear()
    hooks._handlers.update(handlers)


def _user(db: Session, email: str, **extra: object) -> User:
    user = User(
        email=email, full_name=email.split("@")[0], password="!", date_joined=utcnow()
    )
    for key, value in extra.items():
        setattr(user, key, value)
    db.add(user)
    db.commit()
    return user


def _token(user: User) -> str:
    return tokens.issue(subject=str(user.id), kind="access", now=utcnow())


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user)}"}


def _send(client: TestClient, user: User, **fields: object) -> object:
    files = fields.pop("files", None)
    return client.post(
        "/api/v1/support/messages", headers=_auth(user), data=fields, files=files
    )


def _staff(db: Session) -> User:
    return _user(db, "ofis@example.com", is_staff=True, is_superuser=True)


def test_first_message_writes_the_chat_and_tells_the_office(
    client: TestClient, db: Session, fired: list
) -> None:
    owner = _user(db, "mijoz@example.com")
    screen = client.get("/api/v1/support", headers=_auth(owner)).json()
    assert screen["has_chat"] is False and screen["messages"] == []
    assert screen["cursor"] == ""

    sent = _send(client, owner, body="  Salom  ")
    assert sent.status_code == 201, sent.text
    message = sent.json()["message"]
    assert message["body"] == "Salom"
    assert message["own"] is True and message["who"] == "Siz"
    assert message["editable"] and message["deletable"]

    chat = db.scalar(select(SupportConversation))
    assert chat is not None and chat.last_client_at is not None
    actions = set(db.scalars(select(ActionLog.action)))
    assert actions == {"support_open", "support_reply"}
    stored_id = db.scalar(select(SupportMessage.id))
    assert fired == [(QUESTION_POSTED, {"message_id": stored_id})]

    empty = _send(client, owner, body="   ")
    assert empty.status_code == 400
    assert empty.json()["code"] == "empty_message"
    assert empty.json()["detail"] == "Xabar bo'sh. Matn yozing yoki fayl tanlang."
    too_long = _send(client, owner, body="x" * 2001)
    assert too_long.json()["code"] == "message_too_long"
    mixed = _send(client, owner, body="a", sticker="heart")
    assert mixed.json()["code"] == "mixed_message"
    unknown = _send(client, owner, sticker="nope")
    assert unknown.json()["code"] == "unknown_sticker"


def test_send_key_stores_one_message(client: TestClient, db: Session) -> None:
    owner = _user(db, "mijoz@example.com")
    first = _send(client, owner, body="Bir", send_key="k1")
    again = _send(client, owner, body="Bir", send_key="k1")
    assert first.json()["already_sent"] is False
    assert again.status_code == 201 and again.json() == {
        "already_sent": True,
        "message": None,
    }
    assert len(db.scalars(select(SupportMessage)).all()) == 1


def test_attachments_are_stored_and_only_their_owner_reads_them(
    client: TestClient, db: Session, media_root: Path
) -> None:
    owner = _user(db, "mijoz@example.com")
    stranger = _user(db, "begona@example.com")
    sent = _send(
        client,
        owner,
        body="Ekran",
        files=[
            ("attachments", ("ekran.png", PNG, "image/png")),
            ("attachments", ("hisob.pdf", b"%PDF-1.4", "application/pdf")),
        ],
    )
    assert sent.status_code == 201, sent.text
    message = sent.json()["message"]
    assert message["kind"] == "image"
    assert [item["name"] for item in message["files"]] == ["ekran.png", "hisob.pdf"]
    rows = db.scalars(select(SupportAttachment).order_by(SupportAttachment.position))
    stored = list(rows)
    assert all(row.file.startswith("supportchat/") for row in stored)
    assert all((media_root / row.file).is_file() for row in stored)

    picture = message["files"][0]
    download = client.get(picture["url"], headers=_auth(owner))
    assert download.status_code == 200 and download.content == PNG
    assert download.headers["content-disposition"].startswith("attachment")
    shown = client.get(f"{picture['view_url']}&token={_token(owner)}")
    assert shown.headers["content-type"] == "image/png"
    assert shown.headers["content-disposition"].startswith("inline")
    part = client.get(
        picture["view_url"], headers=_auth(owner) | {"Range": "bytes=0-3"}
    )
    assert part.status_code == 206 and part.content == PNG[:4]
    assert part.headers["content-range"] == f"bytes 0-3/{len(PNG)}"

    assert client.get(picture["url"], headers=_auth(stranger)).status_code == 404
    legacy = f"/api/v1/support/messages/{message['id']}/file"
    assert client.get(legacy, headers=_auth(owner)).status_code == 404
    assert client.get(picture["url"]).status_code == 401


def test_upload_limits_match_the_composer(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.supportchat import routers
    from app.modules.supportchat.services import _files

    owner = _user(db, "mijoz@example.com")
    bad = _send(client, owner, files=[("attachments", ("x.exe", b"MZ", "x"))])
    assert bad.json()["code"] == "unsupported_file_type"
    eleven = [("attachments", (f"{n}.txt", b"a", "text/plain")) for n in range(11)]
    many = _send(client, owner, files=eleven)
    assert many.json()["code"] == "too_many_files"
    assert many.json()["detail"] == "Bitta xabarda eng ko'pi 10 ta fayl."

    monkeypatch.setattr(routers, "MAX_UPLOAD_BYTES", 10)
    monkeypatch.setattr(_files, "MAX_UPLOAD_BYTES", 10)
    big = _send(client, owner, files=[("attachments", ("a.txt", b"a" * 11, "t"))])
    assert big.json()["code"] == "upload_too_large"
    assert big.json()["detail"] == "Fayl juda katta. Eng ko'pi 100 MB."

    monkeypatch.setattr(routers, "MAX_SEND_BYTES", 15)
    monkeypatch.setattr(_files, "MAX_SEND_BYTES", 15)
    together = [("attachments", (f"{n}.txt", b"a" * 8, "t")) for n in range(2)]
    assert _send(client, owner, files=together).json()["code"] == "send_too_large"

    voice = ("voice", ("v.webm", b"ogg", "audio/webm"))
    too_long = _send(client, owner, voice_seconds="301", files=[voice])
    assert too_long.json()["code"] == "voice_refused"
    with_words = _send(client, owner, body="a", voice_seconds="3", files=[voice])
    assert with_words.json()["code"] == "mixed_message"
    spoken = _send(client, owner, voice_seconds="3", files=[voice])
    assert spoken.status_code == 201
    assert spoken.json()["message"]["files"][0]["length"] == "0:03"
    assert db.scalar(select(SupportMessage.kind)) == "voice"
    assert len(db.scalars(select(SupportMessage)).all()) == 1


def test_edit_and_delete_inside_the_window_only(
    client: TestClient, db: Session, media_root: Path
) -> None:
    owner = _user(db, "mijoz@example.com")
    stranger = _user(db, "begona@example.com")
    words = _send(client, owner, body="Birinchi").json()["message"]
    path = f"/api/v1/support/messages/{words['id']}"

    edited = client.patch(path, headers=_auth(owner), json={"body": "Ikkinchi"})
    assert edited.status_code == 200
    assert edited.json()["body"] == "Ikkinchi" and edited.json()["edited_at"]
    assert client.patch(path, headers=_auth(owner), json={"body": ""}).json()[
        "code"
    ] == ("empty_message")
    theirs = client.patch(path, headers=_auth(stranger), json={"body": "x"})
    assert theirs.json()["code"] == "message_not_yours"
    assert client.delete(path, headers=_auth(stranger)).json()["code"] == (
        "message_not_yours"
    )

    sticker = _send(client, owner, sticker="heart").json()["message"]
    refused = client.patch(
        f"/api/v1/support/messages/{sticker['id']}",
        headers=_auth(owner),
        json={"body": "x"},
    )
    assert refused.json()["code"] == "nothing_to_edit"

    with_file = _send(
        client, owner, files=[("attachments", ("a.png", PNG, "image/png"))]
    ).json()["message"]
    stored = media_root / db.scalar(select(SupportAttachment.file))
    gone = client.delete(
        f"/api/v1/support/messages/{with_file['id']}", headers=_auth(owner)
    )
    assert gone.status_code == 200
    assert gone.json()["deleted_at"] and gone.json()["files"] == []
    assert gone.json()["preview"] == "Xabar o'chirildi"
    assert not stored.exists()
    assert db.scalar(select(SupportAttachment)) is None
    again = client.delete(
        f"/api/v1/support/messages/{with_file['id']}", headers=_auth(owner)
    )
    assert again.json()["code"] == "message_gone"

    db.execute(
        update(SupportMessage)
        .where(SupportMessage.id == words["id"])
        .values(created_at=utcnow() - timedelta(hours=25))
    )
    db.commit()
    late = client.patch(path, headers=_auth(owner), json={"body": "Kech"})
    assert late.json()["code"] == "edit_window_closed"
    assert late.json()["detail"] == (
        "Bu xabarni endi o'zgartirib bo'lmaydi: 24 soatdan ko'p vaqt o'tgan."
    )
    assert client.delete(path, headers=_auth(owner)).json()["code"] == (
        "edit_window_closed"
    )


def test_reply_quotes_only_this_chat(client: TestClient, db: Session) -> None:
    owner = _user(db, "mijoz@example.com")
    stranger = _user(db, "begona@example.com")
    theirs = _send(client, stranger, body="Meniki").json()["message"]
    mine = _send(client, owner, body="Savol").json()["message"]
    answer = _send(client, owner, body="Yana", reply_to=mine["id"]).json()["message"]
    assert answer["quote"] == {
        "id": mine["id"],
        "who": "Siz",
        "text": "Savol",
        "gone": False,
    }
    wrong = _send(client, owner, body="x", reply_to=theirs["id"])
    assert wrong.json()["code"] == "reply_target_missing"


def test_office_reply_is_unread_until_the_chat_is_opened(
    client: TestClient, db: Session, fired: list
) -> None:
    owner = _user(db, "mijoz@example.com")
    staff = _staff(db)
    mine = _send(client, owner, body="Savol").json()["message"]
    assert mine["read"] is False
    fired.clear()

    reply = write_to_client(
        db, client=owner, sender=staff, draft=Draft(body="Javob"), now=utcnow()
    )
    assert [name for name, _ in fired] == [REPLY_POSTED]
    widget = client.get("/api/v1/support/widget", headers=_auth(owner)).json()
    assert widget == {"has_chat": True, "unread": True, "preview": "Javob"}

    screen = client.get("/api/v1/support", headers=_auth(owner)).json()
    shown = {row["id"]: row for row in screen["messages"]}
    assert shown[str(reply.id)]["who"] == "Qo'llab-quvvatlash"
    assert shown[str(reply.id)]["own"] is False
    assert shown[mine["id"]]["read"] is True
    widget = client.get("/api/v1/support/widget", headers=_auth(owner)).json()
    assert widget["unread"] is False


def test_poll_answers_204_until_something_changes(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "mijoz@example.com")
    staff = _staff(db)
    assert client.get("/api/v1/support/messages", headers=_auth(owner)).status_code == (
        204
    )
    _send(client, owner, body="Savol")
    cursor = client.get("/api/v1/support", headers=_auth(owner)).json()["cursor"]
    poll = client.get(
        "/api/v1/support/messages", params={"after": cursor}, headers=_auth(owner)
    )
    assert poll.status_code == 204

    write_to_client(
        db, client=owner, sender=staff, draft=Draft(body="Javob"), now=utcnow()
    )
    changed = client.get(
        "/api/v1/support/messages", params={"after": cursor}, headers=_auth(owner)
    )
    assert changed.status_code == 200
    body = changed.json()
    # The boundary message comes again; the page replaces rows by id.
    assert [row["body"] for row in body["messages"]][-1] == "Javob"
    assert body["cursor"] != cursor
    again = client.get(
        "/api/v1/support/messages",
        params={"after": body["cursor"]},
        headers=_auth(owner),
    )
    assert again.status_code == 204


def test_socket_hears_the_office_and_stores_words(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "mijoz@example.com")
    staff = _staff(db)
    _send(client, owner, body="Savol")
    with client.websocket_connect(
        f"/api/v1/support/ws?token={_token(owner)}"
    ) as socket:
        reply = write_to_client(
            db, client=owner, sender=staff, draft=Draft(body="Javob"), now=utcnow()
        )
        live.broadcast_message(message=reply)
        heard = socket.receive_json()
        assert heard["type"] == "message" and heard["id"] == str(reply.id)
        assert heard["message"]["body"] == "Javob"
        assert heard["message"]["who"] == "Qo'llab-quvvatlash"

        live.publish(owner_id=owner.id, event=live.typing_event(side="office"))
        assert socket.receive_json() == {"type": "typing", "side": "office"}

        socket.send_json({"body": "Rahmat", "nonce": "n1"})
        mine = socket.receive_json()
        assert mine["type"] == "message" and mine["nonce"] == "n1"
        assert mine["message"]["body"] == "Rahmat" and mine["message"]["own"]

        socket.send_json({"sticker": "nope", "nonce": "n2"})
        assert socket.receive_json() == {
            "type": "error",
            "message": "Bunday stiker yo'q.",
            "code": "unknown_sticker",
            "nonce": "n2",
        }
    chat = db.scalar(select(SupportConversation))
    db.refresh(chat)
    assert chat.client_read_at is not None and chat.client_read_at >= reply.created_at


def test_socket_refuses_without_a_valid_token(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/support/ws?token=nope") as socket,
    ):
        socket.receive_json()
