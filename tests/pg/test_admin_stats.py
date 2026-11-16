"""The owners' figures in Telegram: the morning card, only in the owners' own
bot and only to the ids in the settings; the other bots keep quiet about
them, and a refused picture becomes text."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from telegramkit import SentMessage, TelegramAPIError

from app.common.config import settings
from app.common.db import utcnow
from app.modules.notifications.routers.webhooks import SECRET_HEADER
from app.modules.notifications.schedule import SCHEDULE
from app.modules.notifications.services import admin_stats, handle_update
from app.modules.notifications.services import owners_respond as owners_module
from app.modules.notifications.services import respond as respond_module
from app.modules.notifications.services import staff_respond as staff_module
from app.modules.notifications.services.admin_card import draw_card
from app.modules.notifications.services.owners_respond import handle_owners_update
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


def _opened(client: CardBot) -> Any:
    @contextmanager
    def opened() -> Iterator[CardBot]:
        yield client

    return opened


@pytest.fixture
def owners(monkeypatch: pytest.MonkeyPatch) -> CardBot:
    """The owners' bot; the customers' and the office's are another fake."""
    client = CardBot()
    monkeypatch.setattr(admin_stats, "owners_bot", _opened(client))
    monkeypatch.setattr(owners_module, "owners_bot", _opened(client))
    monkeypatch.setattr(admin_stats, "owners_bot_configured", lambda: True)
    monkeypatch.setattr(settings, "staff_bot_admin_ids", [ADMIN])
    return client


@pytest.fixture
def others(monkeypatch: pytest.MonkeyPatch) -> CardBot:
    client = CardBot()
    monkeypatch.setattr(staff_module, "staff_bot", _opened(client))
    monkeypatch.setattr(respond_module, "bot", _opened(client))
    return client


def test_the_morning_card_goes_to_every_owner_in_the_owners_bot(
    client: TestClient,
    db: Session,
    owners: CardBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sign_up(client)
    monkeypatch.setattr(settings, "staff_bot_admin_ids", [ADMIN, "5550002"])

    assert admin_stats.deliver_admin_report(db, now=utcnow()) == 2
    assert [name for name, _ in owners.calls] == ["send_photo", "send_photo"]
    assert [fields["chat_id"] for _, fields in owners.calls] == [ADMIN, "5550002"]
    (_, first), _ = owners.calls
    assert first["content"][:3] == JPEG_START
    assert not first.get("caption")


def test_no_token_no_report(
    db: Session, owners: CardBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin_stats, "owners_bot_configured", lambda: False)
    assert admin_stats.deliver_admin_report(db, now=utcnow()) == 0
    assert owners.calls == []


def test_it_goes_out_at_seven_in_the_tashkent_morning() -> None:
    (entry,) = [p for p in SCHEDULE if p.task.endswith("deliver_admin_report_task")]
    assert (entry.minute, entry.hour) == ("0", "2")  # 02:00 UTC = 07:00 +05


def test_the_first_column_is_yesterday(client: TestClient, db: Session) -> None:
    sign_up(client)
    now = utcnow()
    stats = admin_stats.read_stats(db, now=now)
    assert [p.label for p in stats.periods] == ["Kecha", "7 kun", "30 kun"]
    assert stats.periods[0].signups == 0
    later = admin_stats.read_stats(db, now=now + timedelta(days=1))
    assert later.periods[0].signups == 1


def test_a_refused_picture_becomes_text(
    client: TestClient, db: Session, owners: CardBot
) -> None:
    sign_up(client)
    owners.refuse = True

    assert admin_stats.deliver_admin_report(db, now=utcnow()) == 1
    (text,) = owners.texts()
    assert "Oxirgi ro'yxatdan o'tganlar" in text


def test_the_other_bots_no_longer_show_the_figures(
    db: Session, owners: CardBot, others: CardBot
) -> None:
    handle_update(db, payload=_text(ADMIN, "/admin"), now=utcnow())
    handle_staff_update(db, payload=_text(ADMIN, "/stat"), now=utcnow())

    assert owners.calls == []
    assert all(name == "send_message" for name, _ in others.calls)
    assert not any("ro'yxatdan o'tdi" in text for text in others.texts())


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


def test_the_owners_bot_answers_an_owner_with_the_card(
    client: TestClient, db: Session, owners: CardBot
) -> None:
    sign_up(client)

    for command in ("/start", "/admin", "/stat"):
        said = handle_owners_update(db, payload=_text(ADMIN, command), now=utcnow())
        assert said == "card"
    assert [name for name, _ in owners.calls] == [
        "send_photo",
        "send_message",
        "send_photo",
        "send_photo",
    ]
    assert "ofis AI" in owners.texts()[0]


def test_the_owners_bot_tells_a_stranger_their_id_and_nothing_else(
    db: Session, owners: CardBot
) -> None:
    said = handle_owners_update(db, payload=_text("777", "/admin"), now=utcnow())

    assert said == "refused"
    (text,) = owners.texts()
    assert "777" in text and "ro'yxatdan o'tdi" not in text


def test_the_owners_webhook_checks_its_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, queued: list
) -> None:
    monkeypatch.setattr(settings, "owners_bot_token", "1:x")
    monkeypatch.setattr(settings, "owners_bot_webhook_secret", "s3cret")
    url = "/webhooks/telegram/owners/"
    body = _text(ADMIN, "/admin")

    refused = client.post(url, json=body, headers={SECRET_HEADER: "nope"})
    taken = client.post(url, json=body, headers={SECRET_HEADER: "s3cret"})

    assert refused.status_code == 403 and taken.status_code == 200
    assert [name for name, _ in queued if name.endswith("handle_owners_bot_update")]
