"""The day's total with a button per pair, a pair's goals behind it, /hisobot and
/bugun, and the morning's frequency levels - figures only, no model."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from telegramkit import Button, TelegramError

from app.common.cache import cache
from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign, CampaignLaunch
from app.modules.ads.selectors import nightly_due_account_ids
from app.modules.agent.constants import FrequencyLevel, RunStatus
from app.modules.agent.models import AgentRun, FrequencyAlert
from app.modules.billing.models import Plan, Subscription
from app.modules.chat.selectors import daily as daily_module
from app.modules.chat.selectors import daily_book, night_has_passed, weekly_book
from app.modules.integrations.models import AdAccount, PageAccount, PagePair
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.miniapp.constants import NEXT_FIELD
from app.modules.miniapp.routers import safe_next
from app.modules.notifications.keys import daily_list_data
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_for
from app.modules.notifications.selectors.daily import day_book, week_book
from app.modules.notifications.services import announce_frequency as frequency_module
from app.modules.notifications.services import announce_reports as reports_module
from app.modules.notifications.services import commands as commands_module
from app.modules.notifications.services import (
    handle_update,
)
from app.modules.notifications.services import respond as respond_module
from app.modules.notifications.services.announce_frequency import (
    deliver_frequency_for,
)
from app.modules.notifications.services.announce_reports import (
    LIST_MOVED,
    daily_report_audience,
    deliver_daily_report_for,
    deliver_report_for,
    finish_daily_report_for,
    finish_weekly_report_for,
    report_audience,
    unfinished_report_audience,
    unfinished_week_audience,
)
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.compose_daily import list_parts
from app.modules.notifications.services.compose_day_pair import pair_message
from core.chat.day_report import DailyReport, DayBook, DayTotal, Figure
from tests.pg.test_actions_inbox import _owner, _page_with_campaign, _run, _suggestion
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
        (MetricLevel.CAMPAIGN, {"external_id": "c_1"}),
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


def _edits(phone: FakeBot) -> list[dict]:
    return [fields for name, fields in phone.calls if name == "edit_message_text"]


def _cabinet(client: TestClient, db: Session) -> User:
    _auth, user = _owner(client, db)
    account, page = _page_with_campaign(db, user)
    db.add(PagePair(owner_id=user.id, page_id=page.id, ad_account_id=account.id))
    db.commit()
    return user


def _account(db: Session, user: User) -> AdAccount:
    account = db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == user.id, AdAccount.is_current.is_(True)
        )
    )
    assert account is not None
    return account


def _night_ran(db: Session, user: User) -> None:
    """The agent's pass over the night, the last thing a night waits for."""
    db.add(
        AgentRun(
            owner_id=user.id,
            window_days=7,
            status=RunStatus.DONE,
            finished_at=MORNING,
        )
    )
    db.commit()


def _ended() -> datetime:
    """When yesterday ended in Tashkent, where the cabinet's account is."""
    return datetime.combine(MORNING.date(), time.min, tzinfo=UTC) - timedelta(hours=5)


def _destination(web_app: str) -> str:
    return parse_qs(urlparse(web_app).query)[NEXT_FIELD][0]


def _second_pair(
    db: Session, user: User, *, chosen: bool = True, timezone: str = "Asia/Tashkent"
) -> AdAccount:
    """A second page paid from a second account, in the subscription or not."""
    first = _account(db, user)
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == user.id))
    assert page is not None
    account = AdAccount(
        owner_id=user.id,
        connection_id=first.connection_id,
        provider=PROVIDER,
        external_id="act_2",
        name="Ikkinchi",
        currency=first.currency,
        timezone=timezone,
        is_active=True,
    )
    other = PageAccount(
        owner_id=user.id,
        connection_id=page.connection_id,
        provider=PROVIDER,
        external_id="p_2",
        name="Do'kon",
        token_encrypted=b"x",
        token_fingerprint="p2",
        is_active=chosen,
    )
    db.add_all([account, other])
    db.flush()
    if chosen:
        db.add(PagePair(owner_id=user.id, page_id=other.id, ad_account_id=account.id))
    db.commit()
    return account


def _group(
    db: Session,
    user: User,
    account: AdAccount,
    campaign_id: str,
    adset_id: str,
    *,
    spend: int,
    built: bool = True,
    goal: str = "LEAD_GENERATION",
    promoted: dict | None = None,
    delivery: str = "active",
    earlier: int = 0,
    into: Campaign | None = None,
    results: int = 2,
) -> Campaign:
    """A campaign with one group in the mirror, and its money yesterday. A
    group of ``earlier`` days back spent then instead."""
    campaign = into or Campaign(
        owner_id=user.id,
        ad_account_id=account.id,
        provider=PROVIDER,
        external_id=campaign_id,
        name=f"Kampaniya {campaign_id}",
        delivery=delivery,
    )
    db.add(campaign)
    db.flush()
    page = "p_2" if account.external_id == "act_2" else "page_1"
    db.add(
        AdSet(
            owner_id=user.id,
            campaign_id=campaign.id,
            provider=PROVIDER,
            external_id=adset_id,
            name=f"Guruh {adset_id}",
            delivery=delivery,
            optimization_goal_raw=goal,
            promoted_object_raw={"page_id": page, **(promoted or {})},
        )
    )
    if built:
        db.add(
            CampaignLaunch(
                owner_id=user.id,
                ad_account_id=account.id,
                page_id=_page_of(db, user, page).id,
                provider=PROVIDER,
                status="created",
                created_refs={"campaign": campaign_id, "adset": [adset_id]},
            )
        )
    levels = [(MetricLevel.ADSET, adset_id), (MetricLevel.AD, f"a_{adset_id}")]
    if into is None:
        levels.append((MetricLevel.CAMPAIGN, campaign_id))
    for level, external_id in levels:
        db.add(
            MetricsDaily(
                owner_id=user.id,
                provider=PROVIDER,
                ad_account_id=account.id,
                level=level,
                external_id=external_id,
                campaign_external_id=campaign_id,
                adset_external_id=adset_id,
                date=YESTERDAY - timedelta(days=earlier),
                spend_minor=spend or 5000,
                currency=account.currency,
                impressions=4000,
                results_reported=results,
                leads_reported=results,
                synced_at=MORNING,
            )
        )
    db.commit()
    return campaign


def _page_of(db: Session, user: User, external_id: str) -> PageAccount:
    page = db.scalar(
        select(PageAccount).where(
            PageAccount.owner_id == user.id, PageAccount.external_id == external_id
        )
    )
    assert page is not None
    return page


def test_a_pair_s_day_is_its_money_and_what_each_goal_brought(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)

    book = daily_book(db, owner=user, now=MORNING)

    assert book is not None
    (report,) = book.reports
    assert report.day == YESTERDAY
    assert report.spend_minor == 120000
    assert report.here and not report.elsewhere
    assert report.figure.results and not report.figure.uncounted


def test_a_lone_pair_s_day_is_sent_once_with_no_list_in_front_of_it(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)

    assert daily_report_audience(db, now=MORNING) == [str(user.id)]
    assert deliver_daily_report_for(db, owner=user, now=MORNING)
    (message,) = _sent(phone)
    assert "KUNLIK HISOBOT" in message["text"]
    assert "Jami sarf" in message["text"] and "NATIJALAR" in message["text"]
    (opened,) = message["buttons"]
    assert opened.text == "Batafsil — kabinetda"
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


def test_two_pairs_are_a_total_and_a_button_each_with_its_money(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    other = _second_pair(db, user)
    _group(db, user, other, "c_2", "s_2", spend=30000, built=False)
    _linked(db, user)

    deliver_daily_report_for(db, owner=user, now=MORNING)

    (message,) = _sent(phone)
    assert "Jami sarf" in message["text"]
    assert "Bahor" not in message["text"] and "NATIJALAR" not in message["text"]
    first, second, cabinet = message["buttons"]
    assert first.text.endswith("Bahor kafesi") and "Asosiy" not in first.text
    assert first.text[0] == "$" and first.data.startswith("dd:")
    assert second.data.startswith("dd:")
    assert cabinet.text == "Kabinetda ochish"

    handle_update(db, payload=_press("700", first.data, message_id=101), now=MORNING)
    opened = _edits(phone)[-1]
    assert "NATIJALAR" in opened["text"]
    assert "Guruh" not in opened["text"] and "Reklama" not in opened["text"]
    back, following, detail = opened["buttons"]
    assert back.data.startswith("dl:") and following.data == second.data
    assert detail.text == "Batafsil — kabinetda"

    handle_update(db, payload=_press("700", back.data, message_id=101), now=MORNING)
    assert "Jami sarf" in _edits(phone)[-1]["text"]


def test_the_cabinet_button_opens_this_pair_on_this_day(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)

    deliver_daily_report_for(db, owner=user, now=MORNING)

    (opened,) = _sent(phone)[0]["buttons"]
    link = unquote(opened.web_app)
    account = db.scalar(select(AdAccount).where(AdAccount.owner_id == user.id))
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == user.id))
    assert f"start={YESTERDAY}&end={YESTERDAY}" in link
    assert f"pair={page.external_id}" in unquote(link)
    assert account.external_id in unquote(link)
    assert safe_next(_destination(opened.web_app)).startswith("/app/?start=")


def test_every_goal_has_a_line_and_the_lines_add_up_to_the_total(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    account = _account(db, user)
    _group(db, user, account, "c_2", "s_2", spend=20000, goal="LEAD_GENERATION")
    _group(
        db,
        user,
        account,
        "c_3",
        "s_3",
        spend=10000,
        goal="OFFSITE_CONVERSIONS",
        promoted={"custom_event_type": "LEAD"},
    )
    _group(db, user, account, "c_4", "s_4", spend=30000, goal="CONVERSATIONS")
    _group(db, user, account, "c_5", "s_5", spend=40000, goal="THRUPLAY", results=0)

    book = daily_book(db, owner=user, now=MORNING)

    (report,) = book.reports
    assert report.spend_minor == 100000
    text = pair_message(book=book, report=report).text
    assert "Forma murojaati" in text and "Saytdagi murojaat" in text
    assert "Suhbat" in text and "Natijasi sanalmaydi" in text
    assert report.figure.uncounted == "$400,00"


def test_two_pairs_of_one_page_keep_the_account_on_their_buttons(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    first = _account(db, user)
    other = AdAccount(
        owner_id=user.id,
        connection_id=first.connection_id,
        provider=PROVIDER,
        external_id="act_3",
        name="Ikkinchi",
        currency=first.currency,
        timezone=first.timezone,
        is_active=True,
    )
    db.add(other)
    db.flush()
    page = _page_of(db, user, "page_1")
    db.add(PagePair(owner_id=user.id, page_id=page.id, ad_account_id=other.id))
    db.commit()
    _group(db, user, other, "c_2", "s_2", spend=30000, built=False)
    _linked(db, user)

    deliver_daily_report_for(db, owner=user, now=MORNING)

    first_button, second_button, _opened = _sent(phone)[0]["buttons"]
    assert first_button.text.endswith("Bahor kafesi · Asosiy")
    assert second_button.text.endswith("Bahor kafesi · Ikkinchi")


def test_a_goal_the_screens_leave_uncounted_has_meta_s_count_and_its_name(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    account = _account(db, user)
    _group(
        db,
        user,
        account,
        "c_2",
        "s_2",
        spend=20000,
        goal="OFFSITE_CONVERSIONS",
        promoted={"custom_event_type": "COMPLETE_REGISTRATION"},
    )
    _group(
        db,
        user,
        account,
        "c_3",
        "s_3",
        spend=10000,
        goal="MESSAGING_PURCHASE_CONVERSION",
    )
    _group(db, user, account, "c_4", "s_4", spend=5000, goal="AUTOMATIC_OBJECTIVE")

    book = daily_book(db, owner=user, now=MORNING)

    (report,) = book.reports
    text = pair_message(book=book, report=report).text
    assert "Ro'yxatdan o'tish" in text and "Xabar orqali xarid" in text
    assert "Boshqa natija" in text and "Natijasi sanalmaydi" not in text
    assert "Natija: <b>2 ta</b>" in text and "Narxi: <b>$100,00</b>" in text
    assert "<blockquote>" in text


def test_sections_stand_a_blank_line_apart_and_a_name_said_twice_is_said_once(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    account = _account(db, user)
    account.name = "Bahor kafesi"
    db.commit()

    book = daily_book(db, owner=user, now=MORNING)

    (report,) = book.reports
    text = pair_message(book=book, report=report).text
    assert report.title == "Bahor kafesi"
    assert "\n\n" in text and "───" not in text and "\n\n\n" not in text
    assert report.day_text.count(",") == 0
    assert "Akkaunt:" not in text
    assert not book.final and text.rstrip().endswith("yakuniy emas</i>")
    assert report.spend.endswith(",00")


def test_a_group_is_counted_by_its_own_goal_not_its_campaign_s(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    account = _account(db, user)
    campaign = _group(
        db, user, account, "c_2", "s_2", spend=20000, goal="LEAD_GENERATION"
    )
    _group(
        db,
        user,
        account,
        "c_2",
        "s_3",
        spend=30000,
        goal="CONVERSATIONS",
        into=campaign,
    )

    (report,) = daily_book(db, owner=user, now=MORNING).reports

    assert {result.kind for result in report.figure.results} == {"lead", "chat"}


def test_ads_manager_s_money_is_in_the_total_and_split_out_beside_it(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _group(db, user, _account(db, user), "c_2", "s_2", spend=30000, built=False)

    book = daily_book(db, owner=user, now=MORNING)

    (report,) = book.reports
    assert report.spend_minor == 150000
    assert report.here and report.elsewhere and not report.elsewhere_apart
    assert "Platformadan" in pair_message(book=book, report=report).text


def test_an_owner_only_in_ads_manager_is_told_their_day(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _group(db, user, _account(db, user), "c_2", "s_2", spend=30000, built=False)
    _linked(db, user)

    assert deliver_daily_report_for(db, owner=user, now=MORNING)

    (message,) = _sent(phone)
    assert "Ads Manager: <b>$" in message["text"]
    assert "Platformadan" not in message["text"]


def test_a_one_time_plan_sees_ads_manager_as_one_sum(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _group(
        db,
        user,
        _account(db, user),
        "c_2",
        "s_2",
        spend=30000,
        built=False,
        goal="CONVERSATIONS",
    )
    _group(db, user, _account(db, user), "c_3", "s_3", spend=0, built=False, earlier=2)
    plan = db.scalar(
        select(Plan).join(Subscription).where(Subscription.owner_id == user.id)
    )
    plan.is_one_time = True
    db.commit()

    book = daily_book(db, owner=user, now=MORNING)

    (report,) = book.reports
    assert report.spend_minor == 150000 and report.elsewhere_apart
    assert report.idle == 0
    assert {result.kind for result in report.figure.results} == {"lead"}
    assert "Ads Manager" in pair_message(book=book, report=report).text


def test_a_silent_campaign_counts_only_while_it_spent_lately_and_is_on(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    account = _account(db, user)
    _group(db, user, account, "c_2", "s_2", spend=0, built=False, earlier=3)
    _group(db, user, account, "c_3", "s_3", spend=0, built=False, earlier=20)
    _group(
        db,
        user,
        account,
        "c_4",
        "s_4",
        spend=0,
        built=False,
        earlier=3,
        delivery="paused",
    )

    book = daily_book(db, owner=user, now=MORNING)

    (report,) = book.reports
    assert report.idle == 1
    assert "yana 1 ta kampaniya yoniq" in pair_message(book=book, report=report).text


def test_money_on_an_unchosen_page_is_named_and_added_to_nothing(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    other = _second_pair(db, user, chosen=False)
    _group(db, user, other, "c_2", "s_2", spend=30000, built=False)
    _linked(db, user)

    book = daily_book(db, owner=user, now=MORNING)

    (report,) = book.reports
    assert report.spend_minor == 120000 and book.outside
    deliver_daily_report_for(db, owner=user, now=MORNING)
    assert "Tanlanmagan sahifalar" in _sent(phone)[0]["text"]


def test_an_owner_only_on_unchosen_pages_is_still_told(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    other = _second_pair(db, user, chosen=False)
    _group(db, user, other, "c_2", "s_2", spend=30000, built=False)
    _linked(db, user)

    assert deliver_daily_report_for(db, owner=user, now=MORNING)

    (message,) = _sent(phone)
    assert "Tanlanmagan sahifalar" in message["text"]
    assert "Sarf bo'lmagan" in message["text"]


def test_the_day_before_is_beside_the_total_and_not_beside_today_so_far(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _group(db, user, _account(db, user), "c_2", "s_2", spend=0, built=False, earlier=1)

    book = daily_book(db, owner=user, now=MORNING)
    (report,) = book.reports
    assert report.before and book.totals[0].before
    assert report.change == book.totals[0].change
    assert report.change.startswith("+") and report.change.endswith("%")
    assert "Oldingi kun" in pair_message(book=book, report=report).text

    today = daily_book(db, owner=user, now=MORNING, day=YESTERDAY + timedelta(days=1))
    assert all(not report.before for report in today.reports)


def test_a_morning_message_sent_unfinished_is_edited_once_the_night_ends(
    client: TestClient, db: Session, phone: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)
    _night_ran(db, user)
    db.execute(update(MetricsDaily).values(synced_at=_ended() - timedelta(hours=2)))
    db.commit()

    deliver_daily_report_for(db, owner=user, now=MORNING)
    assert "yakuniy emas" in _sent(phone)[0]["text"]
    assert unfinished_report_audience(db, now=MORNING) == []
    assert not finish_daily_report_for(db, owner=user, now=MORNING)

    db.execute(update(MetricsDaily).values(synced_at=MORNING))
    db.commit()
    assert unfinished_report_audience(db, now=MORNING) == [str(user.id)]
    assert finish_daily_report_for(db, owner=user, now=MORNING)

    (edited,) = _edits(phone)
    assert edited["message_id"] == 101 and "yakuniy emas" not in edited["text"]
    assert unfinished_report_audience(db, now=MORNING) == []
    assert len(_sent(phone)) == 1


def test_a_message_sent_final_is_never_edited(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)
    _night_ran(db, user)

    deliver_daily_report_for(db, owner=user, now=MORNING)

    assert "yakuniy emas" not in _sent(phone)[0]["text"]
    assert unfinished_report_audience(db, now=MORNING) == []


def test_a_night_is_over_only_when_every_level_was_read_again(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _night_ran(db, user)
    account = _account(db, user)
    assert night_has_passed(db, owner=user, account=account, now=MORNING)

    db.execute(
        update(MetricsDaily)
        .where(MetricsDaily.level == MetricLevel.AD)
        .values(synced_at=_ended() - timedelta(hours=2))
    )
    db.commit()

    assert not night_has_passed(db, owner=user, account=account, now=MORNING)


def test_a_night_is_over_by_each_account_s_own_clock(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _night_ran(db, user)
    clock = _account(db, user)
    far = _second_pair(db, user, timezone="America/Los_Angeles")
    _group(db, user, far, "c_2", "s_2", spend=30000, built=False)
    # Past Tashkent's night, and still the afternoon of that day over there.
    db.execute(
        update(MetricsDaily)
        .where(MetricsDaily.ad_account_id == far.id)
        .values(synced_at=_ended() + timedelta(hours=2))
    )
    db.commit()

    assert not night_has_passed(db, owner=user, account=clock, now=MORNING)

    db.execute(
        update(MetricsDaily)
        .where(MetricsDaily.ad_account_id == far.id)
        # Past its own end and re-read, in winter time or summer time alike.
        .values(synced_at=_ended() + timedelta(hours=15))
    )
    db.commit()
    assert night_has_passed(db, owner=user, account=clock, now=MORNING)


def test_the_night_read_follows_each_account_s_clock_not_the_owner_s(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    near = _account(db, user)
    far = _second_pair(db, user, timezone="America/Los_Angeles")
    night_in_tashkent = MORNING.replace(hour=20)

    due = nightly_due_account_ids(db, now=night_in_tashkent, hour=1)

    assert near.id in due and far.id not in due


def test_a_pair_s_button_from_a_message_no_one_can_read_any_more_says_so(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)

    data = f"dd:{YESTERDAY:%Y%m%d}:0123456789"
    assert handle_update(
        db, payload=_press("700", data, message_id=9), now=MORNING
    ) == ("daily_gone")


def test_hisobot_sends_yesterday_and_bugun_says_today_is_quiet(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _spent(db, user)
    _linked(db, user)

    assert handle_update(db, payload=_text("700", "/hisobot"), now=MORNING) == (
        "report_sent"
    )
    assert "KUNLIK HISOBOT" in _sent(phone)[-1]["text"]
    assert handle_update(db, payload=_text("700", "/bugun"), now=MORNING) == (
        "report_quiet"
    )
    assert "Bugun hali" in _sent(phone)[-1]["text"]


def test_the_frequency_levels_carry_their_two_answers(
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
    # TZ 6.3: the copy window on the site, and the answer pressed right here.
    add, fine = message["buttons"]
    assert add.text == "Qo'shimcha kreativ qo'shamiz" and add.web_app
    assert fine.text == "Reklama yaxshi ishlayapti" and fine.data
    assert "Batafsil" not in message["text"]
    row = db.scalar(select(FrequencyAlert))
    assert row is not None and row.telegram_sent_at is not None
    assert not deliver_frequency_for(db, owner=user, now=MORNING)

    assert (
        handle_update(db, payload=_press("700", fine.data, message_id=101), now=MORNING)
        == "frequency_fine"
    )
    db.expire_all()
    row = db.scalar(select(FrequencyAlert))
    assert row is not None and row.answer == "working_well"


def test_a_frequency_line_left_as_it_is_is_not_told(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    from app.modules.notifications.selectors.inbox_frequency import frequency_key
    from app.modules.notifications.services import leave_item

    user = _cabinet(client, db)
    _linked(db, user)
    account = db.scalar(select(AdAccount).where(AdAccount.owner_id == user.id))
    assert account is not None
    alert = FrequencyAlert(
        owner_id=user.id,
        provider=PROVIDER,
        ad_account_id=account.id,
        adset_external_id="s_1",
        name="Guruh",
        level=FrequencyLevel.WARNING,
        frequency=340,
        currency="USD",
    )
    db.add(alert)
    db.commit()
    leave_item(db, owner=user, key=frequency_key(alert), note="t", now=MORNING)
    db.commit()

    assert not deliver_frequency_for(db, owner=user, now=MORNING)
    assert _sent(phone) == []


def test_a_final_day_is_kept_for_its_buttons_and_comes_back_the_same(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daily_module, "night_has_passed", lambda *a, **k: True)
    user = _cabinet(client, db)
    _spent(db, user)

    built = day_book(db, owner=user, now=MORNING)
    assert built and built.final
    # What Redis gives back: the kept value as JSON read again.
    store = cache._data  # type: ignore[attr-defined]
    for key, (value, expires) in list(store.items()):
        store[key] = (json.loads(json.dumps(value)), expires)
    monkeypatch.setattr(daily_module, "day_tables", None)  # read from the cache
    kept = day_book(db, owner=user, now=MORNING)

    assert kept == built


def _monday() -> datetime:
    """The Monday of this week at 10:00 in Tashkent."""
    return MORNING - timedelta(days=(MORNING + timedelta(hours=5)).weekday())


def _sunday(monday: datetime) -> date:
    return (monday + timedelta(hours=5)).date() - timedelta(days=1)


def _week(
    db: Session,
    user: User,
    account: AdAccount,
    campaign_id: str,
    adset_id: str,
    *,
    spend: int,
    goal: str = "LEAD_GENERATION",
    built: bool = True,
    results: int = 2,
    before: bool = True,
) -> None:
    """A week of a group's money, and the week before it at half the money."""
    monday = _monday()
    sunday = _sunday(monday)
    if not db.scalar(select(Campaign).where(Campaign.external_id == campaign_id)):
        _group(
            db, user, account, campaign_id, adset_id, spend=0, goal=goal, built=built
        )
        db.execute(
            delete(MetricsDaily).where(MetricsDaily.adset_external_id == adset_id)
        )
    for back in range(14 if before else 7):
        for level, external_id in (
            (MetricLevel.ADSET, adset_id),
            (MetricLevel.CAMPAIGN, campaign_id),
            (MetricLevel.AD, f"a_{adset_id}"),
        ):
            db.add(
                MetricsDaily(
                    owner_id=user.id,
                    provider=PROVIDER,
                    ad_account_id=account.id,
                    level=level,
                    external_id=external_id,
                    campaign_external_id=campaign_id,
                    adset_external_id=adset_id,
                    date=sunday - timedelta(days=back),
                    spend_minor=spend if back < 7 else spend // 2,
                    currency=account.currency,
                    impressions=2000,
                    results_reported=results,
                    leads_reported=results,
                    synced_at=monday,
                )
            )
    db.commit()


def test_monday_s_week_is_sent_once_with_its_goals_against_the_week_before(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000, goal="CONVERSATIONS")
    monday = _monday()

    assert report_audience(db, now=monday) == [str(user.id)]
    assert deliver_report_for(db, owner=user, now=monday)

    (message,) = _sent(phone)
    assert "HAFTALIK HISOBOT" in message["text"]
    assert "14 ta" in message["text"]
    assert "Oldingi hafta: 14 ta · $" in message["text"]
    assert "Oldingi hafta: <b>$" in message["text"]
    (opened,) = message["buttons"]
    assert opened.text == "Batafsil — kabinetda"
    sunday = _sunday(monday)
    link = unquote(opened.web_app)
    assert f"start={sunday - timedelta(days=6)}&end={sunday}" in link
    assert report_audience(db, now=monday + timedelta(hours=1)) == []


def test_two_pairs_are_one_message_of_the_week_with_a_button_each(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000)
    other = _second_pair(db, user)
    _week(db, user, other, "c_3", "s_3", spend=5000, built=False)
    monday = _monday()

    deliver_report_for(db, owner=user, now=monday)

    (message,) = _sent(phone)
    assert "Jami sarf" in message["text"] and "Oldingi hafta" in message["text"]
    first, second, _cabinet_button = message["buttons"]
    assert first.data.startswith("wd:") and first.text[0] == "$"

    handle_update(db, payload=_press("700", first.data, message_id=101), now=monday)
    opened = _edits(phone)[-1]
    assert "NATIJALAR" in opened["text"]
    back, following, _detail = opened["buttons"]
    assert back.data.startswith("wl:") and following.data == second.data

    handle_update(db, payload=_press("700", back.data, message_id=101), now=monday)
    assert "HAFTALIK HISOBOT" in _edits(phone)[-1]["text"]


def test_an_owner_only_in_ads_manager_is_told_their_week(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000, built=False)

    assert deliver_report_for(db, owner=user, now=_monday())

    assert "Ads Manager" in _sent(phone)[0]["text"]


def test_a_goal_says_when_the_week_before_had_nothing_or_no_results(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    account = _account(db, user)
    _week(
        db, user, account, "c_2", "s_2", spend=10000, goal="CONVERSATIONS", before=False
    )
    _week(db, user, account, "c_3", "s_3", spend=10000, goal="QUALITY_CALL", results=0)
    monday = _monday()

    book = weekly_book(db, owner=user, now=monday)

    (report,) = book.reports
    text = pair_message(book=book, report=report).text
    assert "Oldingi hafta: yo'q" in text and "Oldingi hafta: natija yo'q" in text


def test_the_week_s_money_adds_up_with_a_goal_nothing_counts(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    account = _account(db, user)
    _week(db, user, account, "c_2", "s_2", spend=10000)
    _week(db, user, account, "c_3", "s_3", spend=2000, goal="THRUPLAY", results=0)

    (report,) = weekly_book(db, owner=user, now=_monday()).reports

    assert report.spend_minor == 84000 and report.figure.uncounted


def test_a_waiting_proposal_is_counted_on_its_pair(
    client: TestClient, db: Session
) -> None:
    user = _cabinet(client, db)
    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000)
    _suggestion(db, user, _run(db, user), target_external_id="s_2")

    book = weekly_book(db, owner=user, now=_monday())

    (report,) = book.reports
    assert report.open_proposals == 1
    assert (
        "Javob kutayotgan takliflar: 1" in pair_message(book=book, report=report).text
    )


def test_hafta_sends_the_last_week_and_a_quiet_week_says_so(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)

    assert handle_update(db, payload=_text("700", "/hafta"), now=_monday()) == (
        "report_quiet"
    )
    assert "O'tgan haftada" in _sent(phone)[-1]["text"]

    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000)
    assert handle_update(db, payload=_text("700", "/hafta"), now=_monday()) == (
        "report_sent"
    )
    assert "HAFTALIK HISOBOT" in _sent(phone)[-1]["text"]


def test_a_quiet_week_is_marked_done_without_a_message(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)

    assert not deliver_report_for(db, owner=user, now=_monday())
    assert _sent(phone) == []
    assert report_audience(db, now=_monday()) == []


def test_a_monday_message_sent_unfinished_is_edited_once_the_night_ends(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    _night_ran(db, user)
    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000)
    monday = _monday()
    ended = monday.replace(hour=0) - timedelta(hours=5)
    db.execute(update(MetricsDaily).values(synced_at=ended - timedelta(hours=2)))
    db.commit()

    deliver_report_for(db, owner=user, now=monday)
    assert "yakuniy emas" in _sent(phone)[0]["text"]
    assert unfinished_week_audience(db, now=monday) == []

    db.execute(update(MetricsDaily).values(synced_at=monday))
    db.commit()
    assert unfinished_week_audience(db, now=monday) == [str(user.id)]
    assert finish_weekly_report_for(db, owner=user, now=monday)

    (edited,) = _edits(phone)
    assert edited["message_id"] == 101 and "yakuniy emas" not in edited["text"]
    assert unfinished_week_audience(db, now=monday) == []
    assert len(_sent(phone)) == 1


def test_a_week_sent_unfinished_is_settled_by_the_day_after_its_monday(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000)
    monday = _monday()
    db.execute(update(MetricsDaily).values(synced_at=monday - timedelta(days=3)))
    db.commit()
    deliver_report_for(db, owner=user, now=monday)

    assert unfinished_week_audience(db, now=monday + timedelta(days=1)) == [
        str(user.id)
    ]


def test_a_final_week_comes_back_the_same_from_the_cache(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daily_module, "night_has_passed", lambda *a, **k: True)
    user = _cabinet(client, db)
    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000)

    built = week_book(db, owner=user, now=_monday())
    store = cache._data  # type: ignore[attr-defined]
    for key, (value, expires) in list(store.items()):
        store[key] = (json.loads(json.dumps(value)), expires)
    monkeypatch.setattr(daily_module, "day_tables", None)

    assert week_book(db, owner=user, now=_monday()) == built


def test_a_week_s_button_for_an_unknown_pair_says_so(
    client: TestClient, db: Session, phone: FakeBot
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    _week(db, user, _account(db, user), "c_2", "s_2", spend=10000)
    data = f"wd:{_sunday(_monday()) - timedelta(days=6):%Y%m%d}:0123456789"

    assert handle_update(
        db, payload=_press("700", data, message_id=9), now=_monday()
    ) == ("daily_gone")


def _many(pairs: int, *, final: bool = True, weekly: bool = False) -> DayBook:
    """A period with this many pairs that spent, biggest first."""
    return DayBook(
        day=YESTERDAY,
        until=YESTERDAY,
        day_text="1-noyabr",
        weekly=weekly,
        final=final,
        totals=(DayTotal(spend="$99,00"),),
        reports=tuple(
            DailyReport(
                day=YESTERDAY,
                day_text="1-noyabr",
                currency="USD",
                pair=f"pair_{number}",
                page=f"Sahifa {number}",
                page_id=f"p_{number}",
                account=f"Akkaunt {number}",
                account_id=f"act_{number}",
                figure=Figure(spend="$1,00", spend_minor=100),
            )
            for number in range(pairs)
        ),
    )


def _pair_buttons(message: dict) -> list[Button]:
    return [button for button in message["buttons"] if button.data]


@pytest.mark.parametrize(
    ("pairs", "sizes"),
    [
        (0, [0]),
        (2, [2]),
        (20, [20]),
        (21, [11, 10]),
        (22, [11, 11]),
        (40, [20, 20]),
        (41, [14, 14, 13]),
    ],
)
def test_pairs_are_shared_out_evenly_past_twenty(pairs: int, sizes: list[int]) -> None:
    book = _many(pairs)
    parts = list_parts(book)
    assert [len(part) for part in parts] == sizes
    assert [item for part in parts for item in part] == list(book.spent)


def test_twenty_one_pairs_are_two_messages_and_only_the_first_has_the_total(
    client: TestClient, db: Session, phone: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    monkeypatch.setattr(reports_module, "day_book", lambda *_a, **_k: _many(21))

    deliver_daily_report_for(db, owner=user, now=MORNING)
    deliver_daily_report_for(db, owner=user, now=MORNING)

    first, second = _sent(phone)
    assert "(1/2)" in first["text"] and "Jami sarf" in first["text"]
    assert "(2/2)" in second["text"] and "Jami sarf" not in second["text"]
    assert len(_pair_buttons(first)) == 11 and len(_pair_buttons(second)) == 10
    assert not {button.data for button in _pair_buttons(first)} & {
        button.data for button in _pair_buttons(second)
    }


def test_a_second_message_refused_is_owed_and_the_first_is_not_sent_again(
    client: TestClient, db: Session, phone: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    monkeypatch.setattr(reports_module, "day_book", lambda *_a, **_k: _many(21))
    accepted = phone.send_message

    def refused(**fields: Any) -> Any:
        if "(2/2)" in fields["text"]:
            raise TelegramError("no")
        return accepted(**fields)

    monkeypatch.setattr(phone, "send_message", refused)
    deliver_daily_report_for(db, owner=user, now=MORNING)
    assert len(_sent(phone)) == 1

    monkeypatch.setattr(phone, "send_message", accepted)
    deliver_daily_report_for(db, owner=user, now=MORNING)

    first, second = _sent(phone)
    assert "(1/2)" in first["text"] and "(2/2)" in second["text"]


@pytest.mark.parametrize(("weekly", "back_prefix"), [(False, "dl:"), (True, "wl:")])
def test_a_pair_on_the_second_message_stays_on_it_and_goes_back_to_it(
    client: TestClient,
    db: Session,
    phone: FakeBot,
    monkeypatch: pytest.MonkeyPatch,
    weekly: bool,
    back_prefix: str,
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    book = _many(21, weekly=weekly)
    for name in ("day_book", "week_book"):
        monkeypatch.setattr(commands_module, name, lambda *_a, **_k: book)
    commands_module.send_yesterday(
        db, client=phone, chat=chat_for(db, owner=user), now=MORNING
    )
    second = _sent(phone)[1]
    own = _pair_buttons(second)

    handle_update(db, payload=_press("700", own[-1].data, message_id=102), now=MORNING)

    back, following, _detail = _edits(phone)[-1]["buttons"]
    assert following.data == own[0].data
    assert back.data.startswith(back_prefix) and back.data.endswith(":1")

    handle_update(db, payload=_press("700", back.data, message_id=102), now=MORNING)

    listed = _edits(phone)[-1]
    assert "(2/2)" in listed["text"]
    assert [button.data for button in _pair_buttons(listed)] == [
        button.data for button in _pair_buttons(second)
    ]


def test_a_part_the_list_no_longer_has_opens_its_last(
    client: TestClient, db: Session, phone: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    monkeypatch.setattr(commands_module, "day_book", lambda *_a, **_k: _many(5))
    data = daily_list_data(day=YESTERDAY, part=1)

    handle_update(db, payload=_press("700", data, message_id=102), now=MORNING)

    assert "Jami sarf" in _edits(phone)[-1]["text"]


def test_finished_figures_reach_every_message_and_a_grown_list_gets_a_new_one(
    client: TestClient, db: Session, phone: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    monkeypatch.setattr(
        reports_module, "day_book", lambda *_a, **_k: _many(21, final=False)
    )
    deliver_daily_report_for(db, owner=user, now=MORNING)
    assert len(_sent(phone)) == 2

    monkeypatch.setattr(reports_module, "day_book", lambda *_a, **_k: _many(41))
    assert finish_daily_report_for(db, owner=user, now=MORNING)

    assert [edited["message_id"] for edited in _edits(phone)] == [101, 102]
    assert all("yakuniy emas" not in edited["text"] for edited in _edits(phone))
    assert len(_sent(phone)) == 3 and "(3/3)" in _sent(phone)[2]["text"]


def test_a_message_a_shorter_list_no_longer_needs_says_so(
    client: TestClient, db: Session, phone: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _cabinet(client, db)
    _linked(db, user)
    monkeypatch.setattr(
        reports_module, "day_book", lambda *_a, **_k: _many(21, final=False)
    )
    deliver_daily_report_for(db, owner=user, now=MORNING)

    monkeypatch.setattr(reports_module, "day_book", lambda *_a, **_k: _many(20))
    assert finish_daily_report_for(db, owner=user, now=MORNING)

    first, second = _edits(phone)
    assert first["message_id"] == 101 and len(_pair_buttons(first)) == 20
    assert "(1/" not in first["text"]
    assert second["message_id"] == 102 and second["text"] == escaped(LIST_MOVED)
    assert not second["buttons"]
    assert len(_sent(phone)) == 2
