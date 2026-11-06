"""Rassilka: a draft in the office, sent to the bot's chats, the channel and
the site - each only where it was ticked - at Telegram's pace."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import BotClient

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.broadcasts import delivery
from app.modules.broadcasts.constants import BATCH_SIZE
from app.modules.broadcasts.models import Broadcast, BroadcastDelivery
from app.modules.notifications import bot as bot_module
from app.modules.notifications.models import TelegramChat
from tests.pg.conftest import sign_up
from tests.pg.test_office_actions import _staff

OFFICE = "/api/v1/office/broadcasts"
NEWS = "/api/v1/news"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x02\x00\x00\x00\x02\x00"
    b"\x08\x02\x00\x00\x00" + b"\x00" * 64
)
CHANNEL = "@targetolog_news"


class Telegram:
    """The Bot API as a transport: what was asked, and per-chat answers."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.blocked: set[str] = set()
        self.rate_limited_once: set[str] = set()
        self.next_id = 100

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if request.headers["content-type"].startswith("multipart/"):
            body = request.read().decode("latin-1")
            chat = body.split('name="chat_id"\r\n\r\n', 1)[1].split("\r\n", 1)[0]
            fields: dict[str, Any] = {"chat_id": chat, "upload": True}
            if 'name="caption"' in body:
                fields["caption"] = body.split('name="caption"\r\n\r\n', 1)[1].split(
                    "\r\n--", 1
                )[0]
        else:
            fields = json.loads(request.read())
        self.calls.append((method, fields))
        chat = str(fields["chat_id"])
        if chat in self.blocked:
            return httpx.Response(
                403, json={"ok": False, "description": "Forbidden: bot was blocked"}
            )
        if chat in self.rate_limited_once:
            self.rate_limited_once.discard(chat)
            return httpx.Response(
                429,
                json={
                    "ok": False,
                    "description": "Too Many Requests",
                    "parameters": {"retry_after": 2},
                },
            )
        self.next_id += 1
        result: dict[str, Any] = {"message_id": self.next_id, "chat": {"id": chat}}
        if method == "sendPhoto":
            result["photo"] = [{"file_id": "small"}, {"file_id": "PHOTO-ID"}]
        return httpx.Response(200, json={"ok": True, "result": result})

    def to(self, chat: str) -> list[tuple[str, dict[str, Any]]]:
        return [(m, f) for m, f in self.calls if str(f["chat_id"]) == chat]


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Telegram:
    fake = Telegram()

    @contextmanager
    def opened() -> Iterator[BotClient]:
        client = BotClient(
            token="t", client=httpx.Client(transport=httpx.MockTransport(fake.handler))
        )
        yield client

    monkeypatch.setattr(bot_module, "bot", opened)
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "client_bot")
    monkeypatch.setattr(settings, "telegram_channel_id", CHANNEL)
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return fake


def _chat(db: Session, owner: User, chat_id: str, **fields: Any) -> TelegramChat:
    chat = TelegramChat(
        owner_id=owner.id, chat_id=chat_id, linked_at=utcnow(), **fields
    )
    db.add(chat)
    db.commit()
    return chat


def _customer(client: TestClient, db: Session, email: str) -> tuple[User, dict]:
    phone = f"+99890{abs(hash(email)) % 10_000_000:07d}"
    headers = sign_up(client, email=email, phone=phone)
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user, headers


def _form(**fields: Any) -> dict[str, str]:
    base = {
        "title": "Yangi tarif",
        "body": "Endi CRM <bepul> & tez.",
        "to_bot": "true",
        "to_channel": "false",
        "to_site": "false",
    }
    return {key: str(value) for key, value in (base | fields).items()}


def _run_all(db: Session, broadcast_id: str) -> list[delivery.Run]:
    import uuid

    runs = []
    while True:
        with bot_module.bot() as client:
            done = delivery.run(
                db,
                client=client,
                broadcast_id=uuid.UUID(broadcast_id),
                now=utcnow,
                sleep=lambda _: None,
            )
        runs.append(done)
        if not done.more:
            return runs


def test_only_the_superuser_writes_and_a_draft_is_checked_field_by_field(
    client: TestClient, db: Session, telegram: Telegram
) -> None:
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, boss = _staff(db, email="root@office.test", superuser=True)
    _, customer = _customer(client, db, "c@example.com")

    assert client.get(OFFICE, headers=owner).status_code == 404
    assert client.get(OFFICE, headers=customer).status_code == 404
    shell = client.get("/api/v1/office/me", headers=boss).json()
    assert "broadcasts" in shell["sections"]
    assert (
        "broadcasts"
        not in client.get("/api/v1/office/me", headers=owner).json()["sections"]
    )

    refused = client.post(
        OFFICE,
        headers=boss,
        data=_form(title=" ", body=""),
        files={"image": ("x.gif", b"GIF89a", "image/gif")},
    )
    assert refused.status_code == 422
    assert set(refused.json()["problems"]) == {"title", "body", "image"}

    listing = client.get(OFFICE, headers=boss).json()
    assert listing["networks"] == {"bot": True, "channel": True, "site": True}
    assert listing["total"] == 0


def test_a_send_reaches_each_ticked_network_once_and_the_bot_at_telegrams_pace(
    client: TestClient,
    db: Session,
    telegram: Telegram,
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    boss_user, boss = _staff(db, email="root@office.test", superuser=True)
    reader, reader_headers = _customer(client, db, "a@example.com")
    blocked_by_reader, _ = _customer(client, db, "b@example.com")
    quiet, _ = _customer(client, db, "q@example.com")
    gone, _ = _customer(client, db, "g@example.com")
    banned, _ = _customer(client, db, "z@example.com")
    slow, _ = _customer(client, db, "s@example.com")
    _chat(db, boss_user, "1")
    _chat(db, reader, "10")
    _chat(db, blocked_by_reader, "20")
    _chat(db, quiet, "30", notify_news=False)
    _chat(db, gone, "40", is_active=False)
    _chat(db, banned, "50")
    _chat(db, slow, "60")
    banned.is_active = False
    db.commit()
    telegram.blocked.add("20")
    telegram.rate_limited_once.add("60")

    created = client.post(
        OFFICE,
        headers=boss,
        data=_form(to_channel="true", to_site="true"),
        files={"image": ("cover.png", PNG, "image/png")},
    )
    assert created.status_code == 200, created.text
    broadcast_id = created.json()["id"]
    draft = client.get(f"{OFFICE}/{broadcast_id}", headers=boss).json()
    assert draft["status"] == "draft"
    assert client.get(draft["image_url"]).content == PNG
    assert client.get(NEWS, headers=reader_headers).json()["rows"] == []

    tested = client.post(f"{OFFICE}/{broadcast_id}/test", headers=boss)
    assert tested.status_code == 200, tested.text
    [(method, fields)] = telegram.to("1")
    assert method == "sendPhoto" and fields["upload"]
    assert (
        fields["caption"] == "<b>Yangi tarif</b>\n\nEndi CRM &lt;bepul&gt; &amp; tez."
    )

    assert client.get(f"{OFFICE}/recipients", headers=boss).json() == {"bot": 4}
    sent = client.post(f"{OFFICE}/{broadcast_id}/send", headers=boss)
    assert sent.status_code == 200, sent.text
    assert sent.json()["bot_chats"] == 4
    assert sent.json()["status"] == "sending"
    assert queued == [
        ("app.modules.broadcasts.tasks.deliver_broadcast_task", (broadcast_id,))
    ]
    again = client.post(f"{OFFICE}/{broadcast_id}/send", headers=boss)
    assert again.status_code == 409
    assert (
        client.put(f"{OFFICE}/{broadcast_id}", headers=boss, data=_form()).status_code
        == 409
    )
    assert client.delete(f"{OFFICE}/{broadcast_id}", headers=boss).status_code == 409

    _run_all(db, broadcast_id)

    [(method, fields)] = telegram.to(CHANNEL)
    assert method == "sendPhoto"
    # Uploaded once for the channel and once for the test; the chats get the id.
    assert telegram.to("10") == [
        (
            "sendPhoto",
            {
                "chat_id": "10",
                "photo": "PHOTO-ID",
                "caption": "<b>Yangi tarif</b>\n\nEndi CRM &lt;bepul&gt; &amp; tez.",
                "parse_mode": "HTML",
            },
        )
    ]
    assert (
        telegram.to("30") == [] and telegram.to("40") == [] and telegram.to("50") == []
    )
    assert len(telegram.to("60")) == 2

    shown = client.get(f"{OFFICE}/{broadcast_id}", headers=boss).json()
    assert shown["status"] == "sent"
    assert shown["channel"] == {"posted": True, "error": ""}
    assert {k: shown["bot"][k] for k in ("total", "sent", "blocked", "pending")} == {
        "total": 4,
        "sent": 3,
        "blocked": 1,
        "pending": 0,
    }
    db.expire_all()
    assert (
        db.scalar(select(TelegramChat).where(TelegramChat.chat_id == "20")).is_active
        is False
    )

    news = client.get(NEWS, headers=reader_headers).json()
    assert [row["title"] for row in news["rows"]] == ["Yangi tarif"]
    assert news["unread"] == 1 and news["rows"][0]["is_unread"] is True
    assert client.get(news["rows"][0]["image_url"]).content == PNG
    assert client.post(f"{NEWS}/seen", headers=reader_headers).json() == {"unread": 0}
    assert client.get(f"{NEWS}/unread", headers=reader_headers).json() == {"unread": 0}

    assert client.delete(f"{OFFICE}/{broadcast_id}", headers=boss).status_code == 200
    assert client.get(NEWS, headers=reader_headers).json()["rows"] == []
    assert db.scalar(select(BroadcastDelivery.id)) is None


def test_only_the_bot_ticked_reaches_only_the_bot(
    client: TestClient, db: Session, telegram: Telegram
) -> None:
    _, boss = _staff(db, email="root@office.test", superuser=True)
    reader, headers = _customer(client, db, "a@example.com")
    _chat(db, reader, "10")
    long_body = "uzun " * 400
    created = client.post(
        OFFICE,
        headers=boss,
        data=_form(body=long_body),
        files={"image": ("cover.png", PNG, "image/png")},
    ).json()
    client.post(f"{OFFICE}/{created['id']}/send", headers=boss)
    _run_all(db, created["id"])

    assert telegram.to(CHANNEL) == []
    assert client.get(NEWS, headers=headers).json()["rows"] == []
    # Too long to sit under the picture: the picture, then the text.
    methods = [method for method, _ in telegram.to("10")]
    assert methods == ["sendPhoto", "sendMessage"]
    assert "caption" not in telegram.to("10")[0][1]


def test_site_only_is_sent_at_once_and_a_stop_ends_the_bot_send(
    client: TestClient,
    db: Session,
    telegram: Telegram,
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    _, boss = _staff(db, email="root@office.test", superuser=True)
    site = client.post(
        OFFICE, headers=boss, data=_form(to_bot="false", to_site="true")
    ).json()
    done = client.post(f"{OFFICE}/{site['id']}/send", headers=boss).json()
    assert done["status"] == "sent" and queued == []
    assert telegram.calls == []

    nothing = client.post(OFFICE, headers=boss, data=_form(to_bot="false")).json()
    refused = client.post(f"{OFFICE}/{nothing['id']}/send", headers=boss)
    assert refused.status_code == 422 and "networks" in refused.json()["problems"]

    for number in range(BATCH_SIZE + 5):
        user = User(email=f"u{number}@example.com", password="!", date_joined=utcnow())
        db.add(user)
        db.flush()
        db.add(
            TelegramChat(
                owner_id=user.id, chat_id=str(1000 + number), linked_at=utcnow()
            )
        )
    db.commit()
    bot = client.post(OFFICE, headers=boss, data=_form()).json()
    client.post(f"{OFFICE}/{bot['id']}/send", headers=boss)
    import uuid

    with bot_module.bot() as tg:
        first = delivery.run(
            db,
            client=tg,
            broadcast_id=uuid.UUID(bot["id"]),
            now=utcnow,
            sleep=lambda _: None,
        )
    assert first.more is True
    stopped = client.post(f"{OFFICE}/{bot['id']}/stop", headers=boss).json()
    assert stopped["status"] == "stopped"
    assert stopped["bot"]["sent"] == BATCH_SIZE and stopped["bot"]["pending"] == 5
    assert _run_all(db, bot["id"])[-1].more is False
    assert len(telegram.calls) == BATCH_SIZE
    assert db.get(Broadcast, uuid.UUID(bot["id"])).status == "stopped"


def test_saving_the_other_switches_keeps_the_news_switch(
    client: TestClient, db: Session, telegram: Telegram
) -> None:
    reader, headers = _customer(client, db, "a@example.com")
    chat = _chat(db, reader, "10")
    off = client.post(
        "/api/v1/notifications/preferences",
        headers=headers,
        json={"notify_news": False},
    )
    assert off.status_code == 200 and off.json()["chat"]["notify_news"] is False
    client.post(
        "/api/v1/notifications/preferences",
        headers=headers,
        json={"notify_report": True},
    )
    db.refresh(chat)
    assert chat.notify_news is False
