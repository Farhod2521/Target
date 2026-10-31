"""A survey asked in the bot - press, typed words, «Keyinroq» - and a question
typed in the bot answered there by the assistant, with no button that writes."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.notifications import bot as bot_module
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.services import announce_survey as survey_module
from app.modules.notifications.services import converse as converse_module
from app.modules.notifications.services import handle_update
from app.modules.notifications.services import respond as respond_module
from app.modules.notifications.services.announce_survey import (
    deliver_survey_for,
    resend_survey_for,
)
from app.modules.notifications.services.converse import answer_and_send
from app.modules.surveys.models import SurveyResponse
from tests.pg.test_office_telegram import FakeBot, _press, _text
from tests.pg.test_surveys import _customer, _survey

# Noon in Tashkent: inside the asking hours.
NOON = datetime.now(UTC).replace(hour=7, minute=0, second=0, microsecond=0)
TASK = "app.modules.notifications.tasks."


@pytest.fixture
def phone(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()
    client.send_chat_action = lambda **fields: None  # type: ignore[attr-defined]

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    for module in (survey_module, respond_module, bot_module):
        monkeypatch.setattr(module, "bot", opened)
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "client_bot")
    monkeypatch.setattr(settings, "site_url", "https://targetolog.test")
    return client


def _linked(db: Session, user: User) -> TelegramChat:
    chat = TelegramChat(
        owner_id=user.id, chat_id="700", is_active=True, linked_at=utcnow()
    )
    db.add(chat)
    db.commit()
    return chat


def _sent(phone: FakeBot) -> list[dict]:
    return [fields for name, fields in phone.calls if name == "send_message"]


def _button(message: dict, text: str):  # type: ignore[no-untyped-def]
    return next(button for button in message["buttons"] if button.text == text)


def test_a_survey_is_answered_in_the_bot_press_by_press(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    _auth, user = _customer(client, db)
    _survey(db)
    _linked(db, user)

    assert deliver_survey_for(db, owner=user, now=NOON) == "sent"
    first = _sent(phone)[-1]
    assert "Fikringiz" in first["text"] and "Yordam berdimi?" in first["text"]

    no = _button(first, "Yo'q")
    handle_update(db, payload=_press("700", no.data, message_id=101), now=NOON)
    assert "Nega?" in _sent(phone)[-1]["text"]

    assert (
        handle_update(db, payload=_text("700", "Qimmat", message_id=9), now=NOON)
        == "survey_next"
    )
    mark = _sent(phone)[-1]
    assert "Baho" in mark["text"]

    seven = _button(mark, "7")
    assert (
        handle_update(db, payload=_press("700", seven.data, message_id=103), now=NOON)
        == "survey_answered"
    )
    response = db.scalar(select(SurveyResponse))
    assert response is not None and response.channel == "bot"
    assert "Rahmat" in _sent(phone)[-1]["text"]
    assert deliver_survey_for(db, owner=user, now=NOON) == "answered_today"


def test_later_puts_the_question_off_and_asks_it_again(
    client: TestClient, db: Session, phone: FakeBot, queued: list
) -> None:
    _auth, user = _customer(client, db)
    _survey(db)
    _linked(db, user)
    deliver_survey_for(db, owner=user, now=NOON)
    later = _button(_sent(phone)[-1], "Keyinroq")

    assert (
        handle_update(db, payload=_press("700", later.data, message_id=101), now=NOON)
        == "survey_later"
    )
    ((name, (owner_id, token)),) = [row for row in queued if "resend" in row[0]]
    assert name == TASK + "resend_survey_task" and owner_id == str(user.id)

    assert resend_survey_for(db, owner=user, token=token, now=NOON) == "sent"
    assert "Yordam berdimi?" in _sent(phone)[-1]["text"]
    # Asked again once: a second wake-up finds the token spent.
    assert resend_survey_for(db, owner=user, token=token, now=NOON) == "stale"


def test_a_typed_question_starts_the_assistant_s_turn(
    client: TestClient, db: Session, phone: FakeBot, queued: list
) -> None:
    _auth, user = _customer(client, db)
    _linked(db, user)

    outcome = handle_update(
        db, payload=_text("700", "Kecha nechta lid keldi?", message_id=11), now=NOON
    )

    assert outcome == "asked"
    assert [name for name, _args in queued if name.endswith("answer_for_telegram")]
    # Telegram's redelivery of the same update starts nothing new.
    again = handle_update(
        db, payload=_text("700", "Kecha nechta lid keldi?", message_id=11), now=NOON
    )
    assert again == "duplicate"


def test_the_answer_is_sent_in_words_with_the_way_to_the_chat(
    db: Session, client: TestClient, phone: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    _auth, user = _customer(client, db)
    _linked(db, user)
    monkeypatch.setattr(
        converse_module, "turn_payload", lambda *, turn_id: {"message_id": "m1"}
    )
    monkeypatch.setattr(converse_module, "answer_turn", lambda db, **kwargs: None)
    monkeypatch.setattr(
        converse_module, "answer_of", lambda db, *, owner, message_id: "Kecha 5 ta lid."
    )
    monkeypatch.setattr(
        converse_module, "offers_on", lambda db, *, owner, message_id: ("choice",)
    )
    monkeypatch.setattr(
        converse_module, "replies_on", lambda db, *, owner, message_id: []
    )

    assert (
        answer_and_send(db, turn_id="t1", chat_id="700", reply_to=11, now=NOON)
        == "answered"
    )
    (message,) = _sent(phone)
    assert "Kecha 5 ta lid." in message["text"] and message["reply_to"] == 11
    (button,) = message["buttons"]
    assert button.text == "Chatda davom etish" and button.web_app and not button.data


def test_without_a_subscription_the_assistant_does_not_answer(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    from tests.pg.conftest import sign_up

    sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    _linked(db, user)

    assert (
        handle_update(db, payload=_text("700", "Salom?", message_id=12), now=NOON)
        == "not_entitled"
    )
    assert "Obuna faol emas" in _sent(phone)[-1]["text"]
