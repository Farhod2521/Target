"""The owners' figures in Telegram: /admin for the ids in the settings, in
either bot and with no cabinet linked, nothing for anybody else, a widget
that fits, and text when it is refused."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from telegramkit import SentMessage, TelegramAPIError, widget_fits

from app.common.config import settings
from app.common.db import utcnow
from app.modules.notifications.services import admin_stats, handle_update
from app.modules.notifications.services import respond as respond_module
from app.modules.notifications.services import staff_respond as staff_module
from app.modules.notifications.services.staff_respond import handle_staff_update
from tests.conftest import SIGNUP
from tests.pg.conftest import sign_up
from tests.pg.test_office_telegram import FakeBot, _text

ADMIN = "5550001"


class WidgetBot(FakeBot):
    refuse = False

    def send_widget(self, **fields: Any) -> SentMessage:
        if self.refuse:
            raise TelegramAPIError("Bad Request: method not found")
        return self._sent("send_widget", **fields)


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> WidgetBot:
    client = WidgetBot()

    @contextmanager
    def opened() -> Iterator[WidgetBot]:
        yield client

    monkeypatch.setattr(staff_module, "staff_bot", opened)
    monkeypatch.setattr(respond_module, "bot", opened)
    monkeypatch.setattr(admin_stats, "bot", opened)
    monkeypatch.setattr(admin_stats, "is_configured", lambda: True)
    monkeypatch.setattr(settings, "staff_bot_admin_ids", [ADMIN])
    return client


def test_an_owner_gets_the_card_in_the_customers_bot_without_linking(
    client: TestClient, db: Session, bot: WidgetBot
) -> None:
    sign_up(client)

    said = handle_update(db, payload=_text(ADMIN, "/admin"), now=utcnow())

    assert said == "widget"
    ((name, fields),) = bot.calls
    assert name == "send_widget" and fields["chat_id"] == ADMIN
    assert widget_fits(fields["html"])
    assert SIGNUP["email"].lower() in fields["html"].lower()
    assert "<b>Bugun:</b> 1 ro'yxatdan o'tdi" in fields["caption"]


def test_the_staff_bot_answers_an_owner_too(
    client: TestClient, db: Session, bot: WidgetBot
) -> None:
    sign_up(client)

    assert handle_staff_update(db, payload=_text(ADMIN, "/stat"), now=utcnow()) == (
        "widget"
    )


def test_a_refused_widget_becomes_text(
    client: TestClient, db: Session, bot: WidgetBot
) -> None:
    sign_up(client)
    bot.refuse = True

    said = handle_update(db, payload=_text(ADMIN, "/admin"), now=utcnow())

    assert said == "text"
    (text,) = bot.texts()
    assert "Oxirgi ro'yxatdan o'tganlar" in text


def test_anybody_else_gets_no_figures(db: Session, bot: WidgetBot) -> None:
    said = handle_update(db, payload=_text("777", "/admin"), now=utcnow())

    assert said == "unknown"
    assert [name for name, _ in bot.calls] == ["send_message"]
    assert "ro'yxatdan o'tdi" not in bot.texts()[0]


def test_the_evening_report_goes_to_every_owner(
    client: TestClient,
    db: Session,
    bot: WidgetBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sign_up(client)
    monkeypatch.setattr(settings, "staff_bot_admin_ids", [ADMIN, "5550002"])

    assert admin_stats.deliver_admin_report(db, now=utcnow()) == 2
    assert [fields["chat_id"] for _, fields in bot.calls] == [ADMIN, "5550002"]


def test_a_long_list_is_cut_until_telegram_takes_it(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    stats = admin_stats.read_stats(db, now=utcnow())
    heavy = stats.__class__(
        **{
            **{f: getattr(stats, f) for f in stats.__dataclass_fields__},
            "signups": tuple(
                admin_stats.Signup(
                    when="01.01 10:00",
                    name=f"Mijoz {n} " + "x" * 40,
                    email=f"user{n}-{'y' * 30}@example.com",
                    phone="",
                )
                for n in range(40)
            ),
        }
    )

    assert widget_fits(admin_stats.fitted_widget(heavy))
