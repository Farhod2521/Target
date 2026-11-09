"""The support bot: an owner's words and files land in their support chat as
if typed there, a stranger's open a guest chat, and the office's replies,
edits and deletes come back into the bot signed with the replier's name."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import BotBlocked, SentMessage, TelegramFile, TelegramRateLimited

from app.common.config import settings
from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.notifications.models import SupportBotChat, TelegramChat
from app.modules.notifications.services import (
    announce_support as announce_module,
)
from app.modules.notifications.services import (
    announce_support_reply,
    deliver_bot_guest_answer,
    deliver_bot_reply,
    handle_support_update,
    handle_update,
    issue_support_link_token,
    mirror_bot_change,
)
from app.modules.notifications.services import (
    respond as respond_module,
)
from app.modules.notifications.services import (
    support_bot as support_bot_module,
)
from app.modules.notifications.services import (
    support_bot_out as support_bot_out_module,
)
from app.modules.supportchat.constants import MessageKind, MessageSource
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.models import (
    SupportAttachment,
    SupportConversation,
    SupportGuestChat,
    SupportGuestMessage,
    SupportMessage,
    SupportRelay,
)
from app.modules.supportchat.services import (
    delete_message,
    edit_message,
    office_answers_guest,
    post_message,
)
from tests.pg.test_office_actions import _staff
from tests.pg.test_supportchat import _auth, _user

SECRET = "s3cret"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeBot:
    """Every call Telegram would have had, and an id for each message."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.next_id = 100
        self.refuse: Exception | None = None

    def _sent(self, name: str, **fields: Any) -> SentMessage:
        self.calls.append((name, fields))
        if self.refuse is not None:
            refusal, self.refuse = self.refuse, None
            raise refusal
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

    def delete_message(self, **fields: Any) -> None:
        self.calls.append(("delete_message", fields))

    def answer_callback_query(self, **fields: Any) -> None:
        self.calls.append(("answer_callback_query", fields))

    def get_file(self, **fields: Any) -> TelegramFile:
        self.calls.append(("get_file", fields))
        return TelegramFile(path="photos/file_1.jpg", size=len(PNG))

    def download_file(self, **fields: Any) -> bytes:
        self.calls.append(("download_file", fields))
        return PNG

    def named(self, name: str) -> list[dict[str, Any]]:
        return [fields for called, fields in self.calls if called == name]

    def texts(self) -> list[str]:
        return [fields["text"] for fields in self.named("send_message")]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    for module in (support_bot_module, support_bot_out_module):
        monkeypatch.setattr(module, "support_bot", opened)
    for module in (announce_module, respond_module):
        monkeypatch.setattr(module, "bot", opened)
    monkeypatch.setattr(settings, "support_bot_token", "t")
    monkeypatch.setattr(settings, "support_bot_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "support_bot_username", "yordam_bot")
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "telegram_bot_username", "client_bot")
    return client


def _message(chat_id: str, message_id: int, **body: Any) -> dict[str, Any]:
    return {
        "update_id": message_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": int(chat_id), "type": "private"},
            "from": {"id": int(chat_id), "username": "ali", "first_name": "Ali"},
            **body,
        },
    }


def _text(chat_id: str, text: str, *, message_id: int = 7, reply_to: int = 0) -> dict:
    payload = _message(chat_id, message_id, text=text)
    if reply_to:
        payload["message"]["reply_to_message"] = {"message_id": reply_to}
    return payload


def _linked_owner(db: Session, *, chat_id: str = "900", email: str = "ega@example.com"):
    """An owner whose Telegram is linked to the main bot already."""
    owner = _user(db, email)
    db.add(
        TelegramChat(
            owner_id=owner.id, chat_id=chat_id, is_active=True, linked_at=utcnow()
        )
    )
    db.commit()
    return owner


def _client_messages(db: Session, owner) -> list[SupportMessage]:  # type: ignore[no-untyped-def]
    return list(
        db.scalars(
            select(SupportMessage)
            .where(SupportMessage.sender_id == owner.id)
            .order_by(SupportMessage.created_at)
        )
    )


def test_an_owner_linked_to_the_main_bot_writes_into_their_chat(
    db: Session, fake: FakeBot, queued: list
) -> None:
    owner = _linked_owner(db)

    assert (
        handle_support_update(
            db, payload=_text("900", "Reklama to'xtadi"), now=utcnow()
        )
        == "sent"
    )
    [stored] = _client_messages(db, owner)
    assert stored.body == "Reklama to'xtadi"
    assert stored.source == MessageSource.SUPPORT_BOT
    row = db.scalar(select(SupportBotChat).where(SupportBotChat.chat_id == "900"))
    assert row is not None and row.owner_id == owner.id and row.name == "Ali"
    relay = db.scalar(select(SupportRelay).where(SupportRelay.bot == "support"))
    assert (
        relay is not None
        and relay.message_id == stored.id
        and relay.telegram_message_id == 7
    )
    assert "Qabul qilindi" in fake.texts()[-1], "the first words are told they arrived"
    assert (
        "app.modules.notifications.tasks.deliver_support_question_task",
        (str(stored.id),),
    ) in queued, "the staff bot copy goes as for the site"

    # The next words a minute later are not answered again, and the same
    # delivery twice is stored once.
    assert (
        handle_support_update(
            db, payload=_text("900", "Yana", message_id=8), now=utcnow()
        )
        == "sent"
    )
    assert (
        handle_support_update(
            db, payload=_text("900", "Yana", message_id=8), now=utcnow()
        )
        == "duplicate"
    )
    assert len(_client_messages(db, owner)) == 2
    assert sum("Qabul qilindi" in text for text in fake.texts()) == 1


def test_a_cabinet_code_links_an_owner_and_refuses_a_manager(
    client: TestClient, db: Session, fake: FakeBot
) -> None:
    owner = _user(db, "ega@example.com")
    manager = _user(db, "menejer@example.com", crm_owner_id=owner.id)

    screen = client.get(
        "/api/v1/notifications/support-bot", headers=_auth(owner)
    ).json()
    assert screen["available"] is True and screen["linked"] is False
    assert screen["url"].startswith("https://t.me/yordam_bot?start=")
    token = screen["url"].rsplit("=", 1)[-1]
    refused = client.get("/api/v1/notifications/support-bot", headers=_auth(manager))
    assert refused.status_code == 403, "a CRM manager never reaches the cabinet's link"

    assert (
        handle_support_update(db, payload=_text("901", f"/start {token}"), now=utcnow())
        == "linked"
    )
    assert "Salom, ega!" in fake.texts()[-1]
    assert (
        handle_support_update(db, payload=_text("902", f"/start {token}"), now=utcnow())
        == "refused"
    ), "a code is spent once"
    after = client.get("/api/v1/notifications/support-bot", headers=_auth(owner)).json()
    assert after["linked"] is True

    manager_code = support_bot_module.SUPPORT_BOT_LINK_KEY.format(token="m")
    support_bot_module.cache.set(manager_code, str(manager.id), 60)
    assert (
        handle_support_update(db, payload=_text("903", "/start m"), now=utcnow())
        == "refused"
    )


def test_a_stranger_writes_into_a_guest_chat_that_moves_on_linking(
    db: Session, fake: FakeBot, queued: list
) -> None:
    assert (
        handle_support_update(db, payload=_text("910", "Parolni unutdim"), now=utcnow())
        == "guest_sent"
    )
    assert (
        handle_support_update(
            db, payload=_text("910", "Yordam bering", message_id=8), now=utcnow()
        )
        == "guest_sent"
    )
    guest = db.scalar(select(SupportGuestChat))
    assert guest is not None and guest.channel == "support_bot" and guest.name == "Ali"
    assert guest.phone == "" and guest.email == ""
    words = list(
        db.scalars(select(SupportGuestMessage).order_by(SupportGuestMessage.created_at))
    )
    assert [word.body for word in words] == ["Parolni unutdim", "Yordam bering"]
    assert sum("yordam xizmatiga yuborildi" in text for text in fake.texts()) == 1

    photo = _message("910", 9, photo=[{"file_id": "p1", "file_size": 10}])
    assert handle_support_update(db, payload=photo, now=utcnow()) == "guest_file"
    assert not fake.named("get_file"), "a guest's file is not fetched"

    owner = _user(db, "ega@example.com")
    token = issue_support_link_token(owner=owner)
    assert (
        handle_support_update(
            db, payload=_text("910", f"/start {token}", message_id=10), now=utcnow()
        )
        == "linked"
    )
    db.refresh(guest)
    assert guest.claimed_by_id == owner.id
    moved = _client_messages(db, owner)
    assert [m.body for m in moved] == ["Parolni unutdim", "Yordam bering"]
    assert {m.source for m in moved} == {MessageSource.SUPPORT_BOT}


def test_an_owners_photo_is_stored_as_a_file(db: Session, fake: FakeBot) -> None:
    owner = _linked_owner(db)
    photo = _message(
        "900",
        11,
        photo=[
            {"file_id": "small", "file_size": 3},
            {"file_id": "big", "file_size": len(PNG)},
        ],
        caption="Shu xato chiqyapti",
    )
    assert handle_support_update(db, payload=photo, now=utcnow()) == "sent"
    assert fake.named("get_file") == [{"file_id": "big"}]
    [stored] = _client_messages(db, owner)
    assert stored.kind == MessageKind.IMAGE and stored.body == "Shu xato chiqyapti"
    [attachment] = db.scalars(select(SupportAttachment)).all()
    assert attachment.original_name == "rasm_11.jpg" and attachment.size_bytes == len(
        PNG
    )

    too_big = _message(
        "900",
        12,
        document={"file_id": "d", "file_name": "a.zip", "file_size": 30 * 1024 * 1024},
    )
    assert handle_support_update(db, payload=too_big, now=utcnow()) == "too_large"
    bad_kind = _message(
        "900", 13, document={"file_id": "d", "file_name": "a.exe", "file_size": 10}
    )
    assert handle_support_update(db, payload=bad_kind, now=utcnow()) == "refused"
    assert len(_client_messages(db, owner)) == 1


def test_an_office_reply_goes_to_the_bot_signed_and_follows_edits(
    db: Session, fake: FakeBot, queued: list
) -> None:
    owner = _linked_owner(db)
    aziz, _ = _staff(db, Role.SUPPORT, email="aziz@office.test")
    aziz.full_name = "Aziz Karimov"
    db.commit()
    handle_support_update(db, payload=_text("900", "Pul yechildi"), now=utcnow())
    [question] = _client_messages(db, owner)
    conversation = db.scalar(select(SupportConversation))
    assert conversation is not None

    reply = post_message(
        db,
        conversation=conversation,
        sender=aziz,
        draft=Draft(body="Tekshiramiz", reply_to=str(question.id)),
        now=utcnow(),
    )
    assert (
        "app.modules.notifications.tasks.deliver_support_bot_reply_task",
        (str(reply.id),),
    ) in queued
    fake.calls.clear()
    assert deliver_bot_reply(db, reply_id=str(reply.id), now=utcnow()) == 1
    assert deliver_bot_reply(db, reply_id=str(reply.id), now=utcnow()) == 0, "sent once"
    [sent] = fake.named("send_message")
    assert sent["chat_id"] == "900" and sent["reply_to"] == 7, (
        "quotes the client's own message"
    )
    assert sent["text"] == "<b>Aziz Karimov</b> · Yordam xizmati\n\nTekshiramiz"
    # The main bot's «Javobni ko'rish» is not sent on top of it.
    assert not announce_support_reply(db, owner=owner, subject="x:never", now=utcnow())

    # A client's Telegram reply to it quotes it on the site.
    copy = db.scalar(select(SupportRelay).where(SupportRelay.message_id == reply.id))
    assert copy is not None and copy.part == "text"
    handle_support_update(
        db,
        payload=_text(
            "900", "Rahmat", message_id=20, reply_to=copy.telegram_message_id
        ),
        now=utcnow(),
    )
    thanks = _client_messages(db, owner)[-1]
    assert thanks.body == "Rahmat" and thanks.reply_to_id == reply.id

    edit_message(
        db,
        message_id=reply.id,
        sender=aziz,
        body="Tekshirdik, qaytarildi",
        now=utcnow(),
    )
    assert (
        "app.modules.notifications.tasks.mirror_support_bot_change_task",
        (str(reply.id),),
    ) in queued
    assert mirror_bot_change(db, message_id=str(reply.id)) == "edited"
    [edited] = fake.named("edit_message_text")
    assert edited["message_id"] == copy.telegram_message_id
    assert edited["text"].endswith("Tekshirdik, qaytarildi")

    delete_message(db, message_id=reply.id, sender=aziz, now=utcnow())
    assert mirror_bot_change(db, message_id=str(reply.id)) == "deleted"
    assert fake.named("delete_message") == [
        {"chat_id": "900", "message_id": copy.telegram_message_id}
    ]


def test_a_reply_with_a_file_sends_the_file_then_the_words(
    db: Session, fake: FakeBot
) -> None:
    owner = _linked_owner(db)
    aziz, _ = _staff(db, Role.SUPPORT, email="aziz@office.test")
    handle_support_update(db, payload=_text("900", "Chek kerak"), now=utcnow())
    photo = _message("900", 30, photo=[{"file_id": "big", "file_size": len(PNG)}])
    handle_support_update(db, payload=photo, now=utcnow())
    [_words, with_file] = _client_messages(db, owner)
    conversation = db.scalar(select(SupportConversation))

    # An office message carrying the client's own file back, to have one on disk.
    attachment = db.scalar(
        select(SupportAttachment).where(SupportAttachment.message_id == with_file.id)
    )
    assert attachment is not None
    reply = post_message(
        db,
        conversation=conversation,
        sender=aziz,
        draft=Draft(body="Mana"),
        now=utcnow(),
    )
    db.add(
        SupportAttachment(
            owner_id=owner.id,
            message_id=reply.id,
            position=0,
            kind=MessageKind.IMAGE,
            file=attachment.file,
            original_name="chek.png",
            size_bytes=attachment.size_bytes,
        )
    )
    db.commit()
    fake.calls.clear()
    assert deliver_bot_reply(db, reply_id=str(reply.id), now=utcnow()) == 2
    assert [name for name, _ in fake.calls] == ["send_photo", "send_message"]
    parts = sorted(
        db.scalars(select(SupportRelay.part).where(SupportRelay.message_id == reply.id))
    )
    assert parts == ["file", "text"]


def test_a_blocked_bot_stops_the_replies_and_the_main_bot_takes_over(
    db: Session, fake: FakeBot
) -> None:
    owner = _linked_owner(db)
    aziz, _ = _staff(db, Role.SUPPORT, email="aziz@office.test")
    handle_support_update(db, payload=_text("900", "Savol"), now=utcnow())
    conversation = db.scalar(select(SupportConversation))
    reply = post_message(
        db,
        conversation=conversation,
        sender=aziz,
        draft=Draft(body="Javob"),
        now=utcnow(),
    )
    fake.refuse = BotBlocked("Forbidden: bot was blocked by the user")
    fake.calls.clear()
    assert deliver_bot_reply(db, reply_id=str(reply.id), now=utcnow()) == 0
    row = db.scalar(select(SupportBotChat))
    assert row is not None and row.is_active is False and row.last_error == "blocked"
    # The client is told in the main bot instead, once for this reply.
    assert [t for t in fake.texts() if "Yordam xizmati javob berdi" in t]
    assert announce_support_reply(db, owner=owner, subject="x:never", now=utcnow())


def test_a_temporary_refusal_is_tried_again_without_sending_files_twice(
    db: Session, fake: FakeBot
) -> None:
    owner = _linked_owner(db)
    aziz, _ = _staff(db, Role.SUPPORT, email="aziz@office.test")
    photo = _message("900", 30, photo=[{"file_id": "big", "file_size": len(PNG)}])
    handle_support_update(db, payload=photo, now=utcnow())
    stored = db.scalar(select(SupportAttachment))
    conversation = db.scalar(select(SupportConversation))
    reply = post_message(
        db,
        conversation=conversation,
        sender=aziz,
        draft=Draft(body="Mana"),
        now=utcnow(),
    )
    db.add(
        SupportAttachment(
            owner_id=owner.id,
            message_id=reply.id,
            position=0,
            kind=MessageKind.IMAGE,
            file=stored.file,
            original_name="chek.png",
            size_bytes=stored.size_bytes,
        )
    )
    db.commit()

    sent_message = fake.send_message

    def busy(**fields: Any) -> SentMessage:
        fake.send_message = sent_message  # type: ignore[method-assign]
        raise TelegramRateLimited("Too Many Requests", retry_after=3)

    fake.send_message = busy  # type: ignore[method-assign]
    fake.calls.clear()
    with pytest.raises(TelegramRateLimited):
        deliver_bot_reply(db, reply_id=str(reply.id), now=utcnow())
    assert [name for name, _ in fake.calls] == ["send_photo"]
    assert deliver_bot_reply(db, reply_id=str(reply.id), now=utcnow()) == 1
    assert [name for name, _ in fake.calls] == ["send_photo", "send_message"], (
        "the retry sends the words only"
    )
    row = db.scalar(select(SupportBotChat))
    assert row is not None and row.is_active is True


def test_a_switched_off_owner_writes_as_a_guest(db: Session, fake: FakeBot) -> None:
    owner = _linked_owner(db)
    handle_support_update(db, payload=_text("900", "Savol"), now=utcnow())
    owner.is_active = False
    db.commit()
    assert (
        handle_support_update(
            db, payload=_text("900", "Kira olmayapman", message_id=8), now=utcnow()
        )
        == "guest_sent"
    )
    assert len(_client_messages(db, owner)) == 1, "nothing more as the blocked account"
    guest = db.scalar(select(SupportGuestChat))
    assert guest is not None and guest.channel == "support_bot"


def test_the_office_answers_a_bot_guest_in_telegram(
    db: Session, fake: FakeBot, queued: list
) -> None:
    handle_support_update(db, payload=_text("910", "Salom"), now=utcnow())
    guest = db.scalar(select(SupportGuestChat))
    aziz, _ = _staff(db, Role.SUPPORT, email="aziz@office.test")
    answer = office_answers_guest(
        db, chat=guest, sender=aziz, body="Salom! Qanday yordam kerak?", now=utcnow()
    )
    assert (
        "app.modules.notifications.tasks.deliver_support_bot_guest_answer_task",
        (str(answer.id),),
    ) in queued
    fake.calls.clear()
    assert deliver_bot_guest_answer(db, message_id=str(answer.id), now=utcnow())
    assert not deliver_bot_guest_answer(db, message_id=str(answer.id), now=utcnow())
    [sent] = fake.named("send_message")
    assert sent["chat_id"] == "910" and sent["text"].endswith("Qanday yordam kerak?")


def test_stop_and_groups(db: Session, fake: FakeBot) -> None:
    _linked_owner(db)
    handle_support_update(db, payload=_text("900", "Savol"), now=utcnow())
    assert (
        handle_support_update(
            db, payload=_text("900", "/stop", message_id=40), now=utcnow()
        )
        == "stopped"
    )
    row = db.scalar(select(SupportBotChat))
    assert row is not None and row.is_active is False
    # Writing again switches it back on.
    handle_support_update(
        db, payload=_text("900", "Yana savol", message_id=41), now=utcnow()
    )
    db.refresh(row)
    assert row.is_active is True

    group = _text("900", "salom", message_id=42)
    group["message"]["chat"] = {"id": -100, "type": "group"}
    assert handle_support_update(db, payload=group, now=utcnow()) == "ignored"


def test_the_main_bot_points_yordam_at_the_support_bot(
    db: Session, fake: FakeBot
) -> None:
    _linked_owner(db, chat_id="950")
    assert (
        handle_update(db, payload=_text("950", "/yordam"), now=utcnow())
        == "support_bot_link"
    )
    [sent] = fake.named("send_message")
    assert sent["buttons"][0].url == "https://t.me/yordam_bot"


def test_the_office_sees_where_a_message_came_from(
    client: TestClient, db: Session, fake: FakeBot
) -> None:
    owner = _linked_owner(db)
    handle_support_update(db, payload=_text("900", "Savol"), now=utcnow())
    _aziz, headers = _staff(db, Role.SUPPORT, email="aziz@office.test")
    conversation = db.scalar(select(SupportConversation))
    screen = client.get(
        f"/api/v1/office/support/{conversation.id}", headers=headers
    ).json()
    assert screen["support_bot"] == {
        "linked": True,
        "username": "ali",
        "last_error": "",
    }
    assert screen["messages"][-1]["source"] == "support_bot"

    handle_support_update(db, payload=_text("910", "Men mehmonman"), now=utcnow())
    guests = client.get(
        "/api/v1/office/support/guests?state=all", headers=headers
    ).json()
    [row] = guests["rows"]
    assert row["channel"] == "support_bot" and row["telegram_username"] == "ali"
    assert owner is not None


def test_the_support_webhook_checks_its_own_secret(
    client: TestClient, fake: FakeBot, queued: list
) -> None:
    body = _text("1", "salom")
    header = "X-Telegram-Bot-Api-Secret-Token"
    assert client.post("/webhooks/telegram/support/", json=body).status_code == 403
    assert (
        client.post("/webhooks/telegram/support/", json=body, headers={header: SECRET})
    ).status_code == 200
    assert [name.rsplit(".", 1)[-1] for name, _ in queued] == [
        "handle_support_bot_update"
    ]


def test_coming_back_to_a_stopped_telegram_takes_the_replies_back(
    db: Session, fake: FakeBot
) -> None:
    owner = _linked_owner(db)
    handle_support_update(db, payload=_text("900", "Savol"), now=utcnow())
    handle_support_update(
        db, payload=_text("900", "/stop", message_id=50), now=utcnow()
    )
    token = issue_support_link_token(owner=owner)
    assert (
        handle_support_update(db, payload=_text("905", f"/start {token}"), now=utcnow())
        == "linked"
    )
    handle_support_update(
        db, payload=_text("900", "Qaytdim", message_id=51), now=utcnow()
    )
    live = {
        row.chat_id: row.is_active
        for row in db.scalars(
            select(SupportBotChat).execution_options(populate_existing=True)
        )
    }
    assert live == {"900": True, "905": False}, "one Telegram gets the replies"
