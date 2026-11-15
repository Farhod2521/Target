"""The owners' figures in Telegram: /admin for the ids in the settings, in
either bot and with no cabinet linked, nothing for anybody else, the card
picture, and text when the picture is refused."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from telegramkit import SentMessage, TelegramAPIError

from app.common.config import settings
from app.common.db import utcnow
from app.modules.notifications.services import admin_stats, handle_update
from app.modules.notifications.services import respond as respond_module
from app.modules.notifications.services import staff_respond as staff_module
from app.modules.notifications.services.admin_card import draw_card
from app.modules.notifications.services.staff_respond import handle_staff_update
from tests.pg.conftest import sign_up
from tests.pg.test_office_telegram import FakeBot, _text

ADMIN = "5550001"
JPEG_START = bytes((0xFF, 0xD8, 0xFF))


class CardBot(FakeBot):
    refuse = False

    def send_photo(self, **fields: Any) -> SentMessage:
        if self.refuse:
            raise TelegramAPIError("Bad Request: wrong file")
        return self._sent("send_photo", **fields)


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> CardBot:
    client = CardBot()

    @contextmanager
    def opened() -> Iterator[CardBot]:
        yield client

    monkeypatch.setattr(staff_module, "staff_bot", opened)
    monkeypatch.setattr(respond_module, "bot", opened)
    monkeypatch.setattr(admin_stats, "bot", opened)
    monkeypatch.setattr(admin_stats, "is_configured", lambda: True)
    monkeypatch.setattr(settings, "staff_bot_admin_ids", [ADMIN])
    return client


def test_an_owner_gets_the_card_in_the_customers_bot_without_linking(
    client: TestClient, db: Session, bot: CardBot
) -> None:
    sign_up(client)

    said = handle_update(db, payload=_text(ADMIN, "/admin"), now=utcnow())

    assert said == "card"
    ((name, fields),) = bot.calls
    assert name == "send_photo" and fields["chat_id"] == ADMIN
    assert fields["content"][:3] == JPEG_START
    assert not fields.get("caption")


def test_the_staff_bot_answers_an_owner_too(
    client: TestClient, db: Session, bot: CardBot
) -> None:
    sign_up(client)

    assert handle_staff_update(db, payload=_text(ADMIN, "/stat"), now=utcnow()) == (
        "card"
    )


def test_a_refused_picture_becomes_text(
    client: TestClient, db: Session, bot: CardBot
) -> None:
    sign_up(client)
    bot.refuse = True

    said = handle_update(db, payload=_text(ADMIN, "/admin"), now=utcnow())

    assert said == "text"
    (text,) = bot.texts()
    assert "Oxirgi ro'yxatdan o'tganlar" in text


def test_anybody_else_gets_no_figures(db: Session, bot: CardBot) -> None:
    said = handle_update(db, payload=_text("777", "/admin"), now=utcnow())

    assert said == "unknown"
    assert [name for name, _ in bot.calls] == ["send_message"]
    assert "ro'yxatdan o'tdi" not in bot.texts()[0]


def test_the_evening_report_goes_to_every_owner(
    client: TestClient,
    db: Session,
    bot: CardBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sign_up(client)
    monkeypatch.setattr(settings, "staff_bot_admin_ids", [ADMIN, "5550002"])

    assert admin_stats.deliver_admin_report(db, now=utcnow()) == 2
    assert [fields["chat_id"] for _, fields in bot.calls] == [ADMIN, "5550002"]


def test_long_names_are_drawn_without_failing(client: TestClient, db: Session) -> None:
    sign_up(client)
    stats = admin_stats.read_stats(db, now=utcnow())
    long = stats.__class__(
        **{
            **{f: getattr(stats, f) for f in stats.__dataclass_fields__},
            "signups": tuple(
                admin_stats.Signup(
                    when="01.01 10:00",
                    name=f"Mijoz {n} " + "x" * 80,
                    email=f"user{n}-{'y' * 60}@example.com",
                    phone="+998901234567",
                )
                for n in range(7)
            ),
        }
    )

    assert draw_card(long)[:3] == JPEG_START
