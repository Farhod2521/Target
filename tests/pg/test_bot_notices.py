"""The sweeps that tell a linked phone what it is owed: proposals and their
outcomes said short with the way to the center, refused adverts, the
subscription running out, the adverts a lapse stopped, a broken connection,
and the cabinet's own troubles once a day."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, LapseHold
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import ProviderConnection
from app.modules.notifications.models import TelegramChat, TelegramNotice
from app.modules.notifications.services import announce_account
from app.modules.notifications.services import sweep as sweep_module
from app.modules.notifications.services.sweep import (
    deliver_expiry_notices,
    deliver_lapse_notices,
    deliver_notices,
    deliver_troubles,
)
from core.inbox import InboxItem
from tests.pg.test_actions_inbox import (
    _owner,
    _page_with_campaign,
    _run,
    _suggestion,
)
from tests.pg.test_office_telegram import FakeBot

# 14:00 in Tashkent, the cabinet's clock: past the morning report.
AFTERNOON = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
# 04:00 in Tashkent: the agent's proposals wait for the morning.
NIGHT = AFTERNOON.replace(hour=23) - timedelta(days=1)


@pytest.fixture
def phone(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    monkeypatch.setattr(sweep_module, "bot", opened)
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "client_bot")
    monkeypatch.setattr(settings, "telegram_mandatory_notices", True)
    monkeypatch.setattr(settings, "telegram_expiry_notices", True)
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


def test_a_proposal_is_said_short_with_the_center_and_no_answer_buttons(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    _auth, user = _owner(client, db)
    _page_with_campaign(db, user)
    _suggestion(db, user, _run(db, user))
    _linked(db, user)

    assert deliver_notices(db, now=AFTERNOON) == 1
    (message,) = _sent(phone)
    assert "Agent taklifi" in message["text"]
    (button,) = message["buttons"]
    assert button.text == "Batafsil"
    assert button.web_app and not button.data

    # Told once: the next quarter hour finds it settled.
    assert deliver_notices(db, now=AFTERNOON + timedelta(minutes=15)) == 0


def test_a_proposal_made_in_the_night_waits_for_the_morning(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    _auth, user = _owner(client, db)
    _page_with_campaign(db, user)
    _suggestion(db, user, _run(db, user))
    _linked(db, user)

    assert deliver_notices(db, now=NIGHT) == 0
    assert _sent(phone) == []


def test_a_refused_advert_is_told_once_with_the_campaign(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    _auth, user = _owner(client, db)
    _page_with_campaign(db, user)
    ad = db.scalar(select(Ad).where(Ad.external_id == "a_1"))
    assert ad is not None
    ad.review_feedback = {"global": {"Rasmda matn ko'p": ""}}
    db.commit()
    _linked(db, user)

    assert deliver_notices(db, now=AFTERNOON) == 1
    assert "Reklama rad etildi" in _sent(phone)[0]["text"]
    assert deliver_notices(db, now=AFTERNOON) == 0


def test_the_subscription_running_out_is_warned_three_days_and_one_day_out(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    _auth, user = _owner(client, db, days=3)
    _linked(db, user)
    now = utcnow()

    assert deliver_expiry_notices(db, now=now) == 1
    assert deliver_expiry_notices(db, now=now) == 0
    assert deliver_expiry_notices(db, now=now + timedelta(days=2)) == 1
    texts = [message["text"] for message in _sent(phone)]
    assert all("Obuna muddati tugayapti" in text for text in texts)
    assert _sent(phone)[0]["buttons"][0].text == "Obunani yangilash"


def test_a_lapse_is_told_when_it_stops_and_again_before_the_removal(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    _auth, user = _owner(client, db, days=-1)
    _linked(db, user)
    now = utcnow()
    db.add(
        LapseHold(
            owner_id=user.id,
            ended_at=now - timedelta(hours=1),
            started_at=now - timedelta(minutes=30),
            delete_after=now + timedelta(days=3),
        )
    )
    db.commit()

    assert deliver_lapse_notices(db, now=now) == 1
    assert deliver_lapse_notices(db, now=now) == 0
    assert deliver_lapse_notices(db, now=now + timedelta(days=2, hours=12)) == 1
    subjects = set(
        db.scalars(
            select(TelegramNotice.subject).where(TelegramNotice.owner_id == user.id)
        )
    )
    assert {subject.rsplit(":", 1)[-1] for subject in subjects} == {"stopped", "last"}


def test_a_broken_connection_is_told_without_asking_the_preferences(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    _auth, user = _owner(client, db)
    _page_with_campaign(db, user)
    connection = db.scalar(select(ProviderConnection))
    assert connection is not None
    connection.status = ConnectionStatus.EXPIRED
    chat = _linked(db, user)
    chat.notify_suggestions = chat.notify_rejections = False
    db.commit()

    assert deliver_notices(db, now=AFTERNOON) == 1
    assert "Facebook ulanishi uzildi" in _sent(phone)[0]["text"]


def test_the_cabinet_s_troubles_are_said_in_the_morning_and_skip_the_rest(
    client: TestClient,
    db: Session,
    phone: FakeBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth, user = _owner(client, db)
    _page_with_campaign(db, user)
    _linked(db, user)
    unfinished = InboxItem(
        key="setup:1", kind="setup", level="warning", title="Sozlash tugamagan", body=""
    )
    proposal = InboxItem(
        key="suggestion:1", kind="suggestion", level="info", title="Taklif", body=""
    )
    # Told in the morning message with its answers; a second, bare copy is noise.
    rise = InboxItem(
        key="price:1:1", kind="price", level="urgent", title="Narx oshdi", body=""
    )
    monkeypatch.setattr(
        announce_account,
        "_lines",
        lambda db, *, owner, now: [(rise, ""), (proposal, ""), (unfinished, "")],
    )
    ten_in_tashkent = AFTERNOON.replace(hour=5)

    assert deliver_troubles(db, now=ten_in_tashkent + timedelta(hours=1)) == 0
    assert deliver_troubles(db, now=ten_in_tashkent) == 1
    assert deliver_troubles(db, now=ten_in_tashkent) == 0
    (message,) = _sent(phone)
    assert "Sozlash tugamagan" in message["text"]
