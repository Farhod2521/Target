"""The daily list a pair a line, a pair's day behind its button, /hisobot and
/bugun, and the morning's frequency levels - figures only, no model."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.agent.constants import FrequencyLevel
from app.modules.agent.models import FrequencyAlert
from app.modules.chat.selectors import daily as daily_module
from app.modules.chat.selectors import daily_reports
from app.modules.integrations.models import AdAccount, PagePair
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors.daily import day_reports
from app.modules.notifications.services import announce_frequency as frequency_module
from app.modules.notifications.services import announce_reports as reports_module
from app.modules.notifications.services import (
    handle_update,
)
from app.modules.notifications.services import respond as respond_module
from app.modules.notifications.services.announce_frequency import (
    deliver_frequency_for,
)
from app.modules.notifications.services.announce_reports import (
    daily_report_audience,
    deliver_daily_report_for,
    deliver_report_for,
    report_audience,
)
from tests.pg.test_actions_inbox import _owner, _page_with_campaign
from tests.pg.test_office_telegram import FakeBot, _press, _text

# 10:00 in Tashkent: the report's latest hour has passed, so it goes out
# whether or not the night's re-read is done.
MORNING = datetime.now(UTC).replace(hour=5, minute=0, second=0, microsecond=0)
YESTERDAY = (MORNING + timedelta(hours=5)).date() - timedelta(days=1)


@pytest.fixture
def phone(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    for module in (reports_module, frequency_module, respond_module):
        monkeypatch.setattr(module, "bot", opened)
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "client_bot")
    monkeypatch.setattr(settings, "site_url", "https://targetolog.test")
    return client


def _spent(db: Session, user: User, *, spend: int = 120000) -> None:
    """Yesterday's money on group s_1 and its advert a_1."""
    account = db.scalar(select(AdAccount).where(AdAccount.owner_id == user.id))
    assert account is not None
    for level, ids in (
        (MetricLevel.ADSET, {"external_id": "s_1"}),
        (MetricLevel.AD, {"external_id": "a_1", "ad_external_id": "a_1"}),
    ):
        db.add(
            MetricsDaily(
                owner_id=user.id,
                provider=PROVIDER,
                ad_account_id=account.id,
                level=level,
                campaign_external_id="c_1",
                adset_external_id="s_1",
                date=YESTERDAY,
                spend_minor=spend,
                currency=account.currency,
                impressions=4000,
                clicks=60,
                inline_link_clicks=50,
                leads_reported=3,
                synced_at=MORNING,
                **ids,
            )
        )
    db.commit()


def _linked(db: Session, user: User) -> TelegramChat:
    chat = TelegramChat(
        owner_id=user.id, chat_id="700", is_active=True, linked_at=utcnow()
    )
    db.add(chat)
    db.commit()
    return chat


def _sent(phone: FakeBot) -> list[dict]:
    return [fields for name, fields in phone.calls if name == "send_message"]


def _cabinet(client: TestClient, db: Session) -> User:
    _auth, user = _owner(client, db)
    account, page = _page_with_campaign(db, user)
    db.add(PagePair(owner_id=user.id, page_id=page.id, ad_account_id=account.id))
    db.commit()
    return user


def test_a_pair_s_day_is_its_money_its_groups_and_its_adverts(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)

    (report,) = daily_reports(db, owner=user, now=MORNING)

    assert report.day == YESTERDAY
    assert report.spend_minor == 120000
    (group,) = report.groups
    assert group.campaign == "Bahor" and group.name == "Guruh" and group.running
    assert [ad.name for ad in group.ads] == ["Reklama"]
    assert report.figure.results and report.figure.counted


def test_the_morning_list_is_sent_once_with_a_button_per_pair(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)

    assert daily_report_audience(db, now=MORNING) == [str(user.id)]
    assert deliver_daily_report_for(db, owner=user, now=MORNING)
    (message,) = _sent(phone)
    assert "Kunlik hisobot" in message["text"]
    assert "Sarflandi" in message["text"]
    pair, opened = message["buttons"]
    assert pair.data.startswith("dd:")
    assert opened.web_app

    # Told: the next hour finds the day done.
    assert daily_report_audience(db, now=MORNING + timedelta(hours=1)) == []
    assert not deliver_daily_report_for(db, owner=user, now=MORNING)


def test_a_quiet_day_is_marked_done_without_a_message(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)

    assert not deliver_daily_report_for(db, owner=user, now=MORNING)
    assert _sent(phone) == []
    assert daily_report_audience(db, now=MORNING) == []


def test_a_pair_s_button_opens_its_day_and_the_list_comes_back(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)
    deliver_daily_report_for(db, owner=user, now=MORNING)
    pair = _sent(phone)[0]["buttons"][0]

    handle_update(db, payload=_press("700", pair.data, message_id=101), now=MORNING)
    edits = [fields for name, fields in phone.calls if name == "edit_message_text"]
    assert "Guruh" in edits[-1]["text"] and "Reklama" in edits[-1]["text"]
    back = edits[-1]["buttons"][0]
    assert back.data.startswith("dl:")

    handle_update(db, payload=_press("700", back.data, message_id=101), now=MORNING)
    edits = [fields for name, fields in phone.calls if name == "edit_message_text"]
    assert "Kunlik hisobot" in edits[-1]["text"]


def test_hisobot_sends_yesterday_and_bugun_says_today_is_quiet(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)

    assert handle_update(db, payload=_text("700", "/hisobot"), now=MORNING) == (
        "report_sent"
    )
    assert "Kunlik hisobot" in _sent(phone)[-1]["text"]
    assert handle_update(db, payload=_text("700", "/bugun"), now=MORNING) == (
        "report_quiet"
    )
    assert "Bugun hali" in _sent(phone)[-1]["text"]


def test_the_frequency_levels_are_said_short_with_the_center(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    account = db.scalar(select(AdAccount).where(AdAccount.owner_id == user.id))
    assert account is not None
    db.add(
        FrequencyAlert(
            owner_id=user.id,
            provider=PROVIDER,
            ad_account_id=account.id,
            adset_external_id="s_1",
            name="Guruh",
            level=FrequencyLevel.WARNING,
            frequency=340,
            currency="USD",
        )
    )
    db.commit()

    assert deliver_frequency_for(db, owner=user, now=MORNING)
    (message,) = _sent(phone)
    (button,) = message["buttons"]
    assert button.text == "Batafsil" and button.web_app and not button.data
    row = db.scalar(select(FrequencyAlert))
    assert row is not None and row.telegram_sent_at is not None
    assert not deliver_frequency_for(db, owner=user, now=MORNING)


def test_a_final_day_is_kept_for_its_buttons_and_comes_back_the_same(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daily_module, "night_has_passed", lambda *a, **k: True)
    user = _cabinet(client, db)
    _spent(db, user)

    built = day_reports(db, owner=user, now=MORNING)
    assert built and all(report.final for report in built)
    # What Redis gives back: the kept value as JSON read again.
    store = cache._data  # type: ignore[attr-defined]
    for key, (value, expires) in list(store.items()):
        store[key] = (json.loads(json.dumps(value)), expires)
    monkeypatch.setattr(daily_module, "day_tables", None)  # read from the cache
    kept = day_reports(db, owner=user, now=MORNING)

    assert kept == built


def test_monday_s_week_is_sent_once_without_a_reading(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    today = MORNING.date()
    monday = MORNING - timedelta(days=today.weekday())
    account = db.scalar(select(AdAccount).where(AdAccount.owner_id == user.id))
    assert account is not None
    for back in range(1, 8):
        db.add(
            MetricsDaily(
                owner_id=user.id,
                provider=PROVIDER,
                ad_account_id=account.id,
                level=MetricLevel.ADSET,
                external_id="s_1",
                campaign_external_id="c_1",
                adset_external_id="s_1",
                date=(monday + timedelta(hours=5)).date() - timedelta(days=back),
                spend_minor=50000,
                currency=account.currency,
                impressions=2000,
                leads_reported=2,
                synced_at=monday,
            )
        )
    db.commit()

    assert report_audience(db, now=monday) == [str(user.id)]
    assert deliver_report_for(db, owner=user, now=monday)
    (message,) = _sent(phone)
    assert "Haftalik hisobot" in message["text"]
    assert message["buttons"][0].text == "Raqamlar"
    assert report_audience(db, now=monday + timedelta(hours=1)) == []
