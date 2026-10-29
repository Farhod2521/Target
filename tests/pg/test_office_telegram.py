"""Support over Telegram: the copy in the staff bot, a reply to it, the held
second reply, the answered mark, the client's phone notice, both webhooks."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import SentMessage

from app.common.config import settings
from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.notifications.models import StaffChat, TelegramChat
from app.modules.notifications.services import (
    announce_support as announce_module,
)
from app.modules.notifications.services import (
    announce_support_answered,
    announce_support_reply,
    forward_support_question,
    handle_staff_update,
    handle_update,
    issue_link_token,
)
from app.modules.notifications.services import (
    respond as respond_module,
)
from app.modules.notifications.services import (
    staff_respond as staff_module,
)
from app.modules.notifications.services import (
    support_answered as answered_module,
)
from app.modules.notifications.services import (
    support_desk as desk_module,
)
from app.modules.supportchat.models import SupportMessage, SupportRelay
from tests.pg.test_office_actions import _staff
from tests.pg.test_supportchat import _send, _user

SECRET = "s3cret"


class FakeBot:
    """Every call Telegram would have had, and an id for each message."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.next_id = 100

    def _sent(self, name: str, **fields: Any) -> SentMessage:
        self.calls.append((name, fields))
        self.next_id += 1
        return SentMessage(message_id=self.next_id, chat_id=fields.get("chat_id", ""))

    def send_message(self, **fields: Any) -> SentMessage:
        return self._sent("send_message", **fields)

    def send_photo(self, **fields: Any) -> SentMessage:
        return self._sent("send_photo", **fields)

    def send_document(self, **fields: Any) -> SentMessage:
        return self._sent("send_document", **fields)

    def edit_message_text(self, **fields: Any) -> None:
        self.calls.append(("edit_message_text", fields))

    def answer_callback_query(self, **fields: Any) -> None:
        self.calls.append(("answer_callback_query", fields))

    def texts(self, name: str = "send_message") -> list[str]:
        return [fields["text"] for called, fields in self.calls if called == name]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    for module in (desk_module, answered_module, staff_module):
        monkeypatch.setattr(module, "staff_bot", opened)
    for module in (announce_module, respond_module):
        monkeypatch.setattr(module, "bot", opened)
    monkeypatch.setattr(settings, "staff_bot_token", "t")
    monkeypatch.setattr(settings, "staff_bot_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "staff_bot_username", "office_bot")
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "telegram_bot_username", "client_bot")
    return client


def _text(chat_id: str, text: str, *, reply_to: int = 0, message_id: int = 7) -> dict:
    message: dict[str, Any] = {
        "message_id": message_id,
        "chat": {"id": int(chat_id), "type": "private"},
        "from": {"id": int(chat_id), "username": "u"},
        "text": text,
    }
    if reply_to:
        message["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": 1, "message": message}


def _press(chat_id: str, data: str, *, message_id: int) -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "q1",
            "from": {"id": int(chat_id)},
            "message": {"message_id": message_id, "chat": {"id": int(chat_id)}},
            "data": data,
        },
    }


def test_a_question_is_copied_answered_from_telegram_and_marked(
    client: TestClient, db: Session, fake: FakeBot, queued: list
) -> None:
    owner = _user(db, "mijoz@example.com")
    aziz, _ = _staff(db, Role.SUPPORT, email="aziz@office.test")
    olim, _ = _staff(db, Role.SUPPORT, email="olim@office.test")
    seller, _ = _staff(db, Role.SALES, email="seller@office.test")
    for member, chat_id in ((aziz, "501"), (olim, "502"), (seller, "503")):
        db.add(
            StaffChat(
                owner_id=member.id, chat_id=chat_id, is_active=True, linked_at=utcnow()
            )
        )
    db.commit()

    _send(client, owner, body="Reklama to'xtadi")
    question = db.scalar(select(SupportMessage))
    assert question is not None
    assert (
        "app.modules.notifications.tasks.deliver_support_question_task",
        (str(question.id),),
    ) in queued
    assert forward_support_question(db, message_id=str(question.id), now=utcnow()) == 2
    assert forward_support_question(db, message_id=str(question.id), now=utcnow()) == 0
    copies = {
        relay.chat_id: relay.telegram_message_id
        for relay in db.scalars(select(SupportRelay))
    }
    assert set(copies) == {"501", "502"}, "only members who answer support"
    assert "Reklama" in fake.texts()[0] and "mijoz@example.com" in fake.texts()[0]

    outcome = handle_staff_update(
        db, payload=_text("501", "Tekshiramiz", reply_to=copies["501"]), now=utcnow()
    )
    assert outcome == "support_replied"
    reply = db.scalar(select(SupportMessage).where(SupportMessage.sender_id == aziz.id))
    assert reply is not None and reply.body == "Tekshiramiz"

    assert announce_support_answered(db, reply_id=str(reply.id), now=utcnow()) == 2
    edits = fake.texts("edit_message_text")
    assert len(edits) == 2 and all("Javob berildi" in text for text in edits)

    held = handle_staff_update(
        db, payload=_text("502", "Men ham", reply_to=copies["502"]), now=utcnow()
    )
    assert held == "support_held"
    prompt = next(
        fields
        for name, fields in fake.calls
        if name == "send_message" and fields.get("buttons")
    )
    send_data = prompt["buttons"][0].data
    sent = handle_staff_update(
        db, payload=_press("502", send_data, message_id=900), now=utcnow()
    )
    assert sent == "support_replied"
    again = handle_staff_update(
        db, payload=_press("502", send_data, message_id=900), now=utcnow()
    )
    assert again == "support_expired"
    assert (
        db.scalar(select(SupportMessage).where(SupportMessage.sender_id == olim.id))
        is not None
    )


def test_the_client_hears_of_a_reply_once_per_stretch(
    db: Session, fake: FakeBot
) -> None:
    owner = _user(db, "mijoz@example.com")
    db.add(
        TelegramChat(
            owner_id=owner.id, chat_id="700", is_active=True, linked_at=utcnow()
        )
    )
    db.commit()
    assert announce_support_reply(db, owner=owner, subject="c:never", now=utcnow())
    assert not announce_support_reply(db, owner=owner, subject="c:never", now=utcnow())
    assert "Yordam xizmati javob berdi" in fake.texts()[0]


def test_the_customer_bot_links_and_passes_words_to_support(
    db: Session, fake: FakeBot
) -> None:
    owner = _user(db, "mijoz@example.com")
    token = issue_link_token(owner=owner)
    payload = {
        "update_id": 3,
        "message": {
            "message_id": 1,
            "chat": {"id": 800, "type": "private"},
            "from": {"id": 800, "username": "m"},
            "text": f"/start {token}",
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }
    assert handle_update(db, payload=payload, now=utcnow()) == "linked"
    chat = db.scalar(select(TelegramChat).where(TelegramChat.chat_id == "800"))
    assert chat is not None and chat.owner_id == owner.id

    help_cmd = payload | {"message": payload["message"] | {"text": "/yordam"}}
    assert handle_update(db, payload=help_cmd, now=utcnow()) == "support_waiting"
    assert handle_update(db, payload=_text("800", "Pul yechildi"), now=utcnow()) == (
        "support_sent"
    )
    asked = db.scalar(select(SupportMessage))
    assert asked is not None and asked.body == "Pul yechildi"
    assert handle_update(db, payload=_text("800", "Yana"), now=utcnow()) == "unknown"


def test_the_webhooks_check_their_own_secret(
    client: TestClient, fake: FakeBot, queued: list
) -> None:
    body = _text("1", "salom")
    header = "X-Telegram-Bot-Api-Secret-Token"
    assert client.post("/webhooks/telegram/", json=body).status_code == 403
    assert (
        client.post("/webhooks/telegram/staff/", json=body, headers={header: "x"})
    ).status_code == 403
    assert (
        client.post("/webhooks/telegram/", json=body, headers={header: SECRET})
    ).status_code == 200
    assert (
        client.post("/webhooks/telegram/staff/", json=body, headers={header: SECRET})
    ).status_code == 200
    assert [name.rsplit(".", 1)[-1] for name, _ in queued] == [
        "handle_telegram_update",
        "handle_staff_telegram_update",
    ]
