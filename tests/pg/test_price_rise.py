"""TZ 1 against PostgreSQL: a group's result three times its usual price, said
once in 72 hours, answered in the cabinet, quiet while it was just edited,
and held against the niche when the account has no history of its own."""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.agent.models import FrequencyAlert, PriceAlert
from app.modules.agent.services.check_prices import check_prices
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.businesses.models import Business, BusinessCategory
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.metrics.models import MetricsDaily
from tests.pg.conftest import sign_up
from tests.pg.test_ads_additions import _signed_in


def _today(account: AdAccount, now: datetime) -> date:
    return now.astimezone(account.tzinfo()).date()


def _day(
    db: Session,
    *,
    owner_id: uuid.UUID,
    account: AdAccount,
    adset_id: str,
    ad_id: str,
    day: date,
    spend: int,
    results: int,
    impressions: int = 10_000,
    link_clicks: int = 200,
) -> None:
    db.add(
        MetricsDaily(
            owner_id=owner_id,
            provider=PROVIDER,
            external_id=ad_id,
            ad_account_id=account.id,
            level="ad",
            campaign_external_id="c_1",
            adset_external_id=adset_id,
            ad_external_id=ad_id,
            object_name=f"Reklama {ad_id}",
            date=day,
            spend_minor=spend,
            currency=account.currency,
            impressions=impressions,
            clicks=link_clicks + 100,
            inline_link_clicks=link_clicks,
            results_reported=results,
            synced_at=utcnow(),
        )
    )


def _old_group(
    db: Session, owner_id: uuid.UUID, campaign: Campaign, adset_id: str = "s_old"
) -> None:
    """An earlier group of the same result, with three adverts that qualify."""
    db.add(
        AdSet(
            owner_id=owner_id,
            provider=PROVIDER,
            external_id=adset_id,
            campaign_id=campaign.id,
            name="Eski guruh",
            delivery="paused",
            status="PAUSED",
            currency="USD",
            synced_at=utcnow(),
        )
    )


def _history(
    db: Session,
    *,
    owner_id: uuid.UUID,
    account: AdAccount,
    now: datetime,
    adset_id: str = "s_old",
    prefix: str = "h",
) -> None:
    """Three earlier adverts at $2 a lead, twenty days back."""
    day = _today(account, now) - timedelta(days=20)
    for number in (1, 2, 3):
        _day(
            db,
            owner_id=owner_id,
            account=account,
            adset_id=adset_id,
            ad_id=f"{prefix}_{number}",
            day=day,
            spend=4_000,
            results=20,
        )


def _window(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    now: datetime,
    spend: int,
    results: int,
) -> None:
    """a_1 over the last three finished days, after a quiet start ten days back."""
    today = _today(account, now)
    db.execute(
        MetricsDaily.__table__.delete().where(
            MetricsDaily.owner_id == owner.id,
            MetricsDaily.ad_external_id == "a_1",
            MetricsDaily.date >= today - timedelta(days=3),
        )
    )
    for back in (1, 2, 3):
        _day(
            db,
            owner_id=owner.id,
            account=account,
            adset_id="s_1",
            ad_id="a_1",
            day=today - timedelta(days=back),
            spend=spend // 3,
            results=results // 3,
            impressions=3_000,
            link_clicks=60,
        )
    db.commit()


def _cabinet(client: TestClient, db: Session) -> tuple[dict[str, str], User, AdAccount]:
    headers, owner, campaign = _signed_in(client, db)
    account = db.get(AdAccount, campaign.ad_account_id)
    assert account is not None
    # The adverts have run for weeks: not new to the mirror tonight.
    db.execute(
        update(Ad)
        .where(Ad.owner_id == owner.id)
        .values(created_at=utcnow() - timedelta(days=30))
    )
    _old_group(db, owner.id, campaign)
    now = utcnow()
    _day(
        db,
        owner_id=owner.id,
        account=account,
        adset_id="s_1",
        ad_id="a_1",
        day=_today(account, now) - timedelta(days=10),
        spend=100,
        results=0,
    )
    db.commit()
    return headers, owner, account


def _open(db: Session) -> list[PriceAlert]:
    db.expire_all()
    return list(db.scalars(select(PriceAlert).where(PriceAlert.closed_at.is_(None))))


def test_three_times_the_usual_price_is_said_once_in_72_hours(
    client: TestClient, db: Session
) -> None:
    headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    # $120 for twelve leads: $10 a lead against $2 - five times.
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)

    (row,) = check_prices(db, owner=owner, now=now)

    assert (row.adset_external_id, row.ad_external_id) == ("s_1", "a_1")
    assert (row.cost_minor, row.cost_usual_minor, row.times) == (1_000, 200, 500)
    assert (row.baseline_source, row.baseline_adverts) == ("account_history", 3)
    assert row.result_kind == "lead"
    # The next night it is still dear: nothing new for 72 hours.
    assert check_prices(db, owner=owner, now=now + timedelta(days=1)) == []
    assert len(_open(db)) == 1

    (item,) = _price_items(client, headers)
    assert item["title"] == "To'xtang, lid narxi oshib ketdi"
    assert (
        "Oldingi reklamalaringizda odatda $2 bo'lgan, ya'ni hozir 5 baravar"
        in item["body"]
    )
    assert [a["label"] for a in item["actions"]] == [
        "Yangi kreativ qo'shish",
        "Reklamani to'xtatish",
        "Kuzataman",
    ]
    watch = item["actions"][2]["href"]
    assert watch == f"/api/v1/agent/price/{row.id}/watch"

    answered = client.post(watch, headers=headers)
    assert answered.status_code == 200, answered.text
    db.expire_all()
    assert db.get(PriceAlert, row.id).answer == "watching"
    assert _price_items(client, headers) == []


def _items_of(inbox: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for value in inbox.values():
        if isinstance(value, list):
            found += [
                each
                for each in value
                if isinstance(each, dict) and each.get("kind") == "price"
            ]
    return found


def _price_items(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    return _items_of(client.get("/api/v1/actions", headers=headers).json())


def test_stop_pauses_the_group_only_on_the_press(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    (row,) = check_prices(db, owner=owner, now=now)
    assert db.scalar(select(ActionLog).where(ActionLog.owner_id == owner.id)) is None

    paused = client.post(f"/api/v1/agent/price/{row.id}/pause", headers=headers)

    assert paused.status_code == 200, paused.text
    log = db.scalar(select(ActionLog).where(ActionLog.owner_id == owner.id))
    assert log is not None
    assert (log.action, log.target_external_id) == (ActionType.PAUSE, "s_1")
    db.expire_all()
    assert db.get(PriceAlert, row.id).answer == "paused"


def test_add_a_creative_opens_the_advert_that_rose(
    client: TestClient, db: Session
) -> None:
    headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    (row,) = check_prices(db, owner=owner, now=now)

    answer = client.get(f"/api/v1/agent/price/{row.id}/creative", headers=headers)

    assert answer.status_code == 200, answer.text
    assert answer.json()["externalId"] == "a_1"


def test_under_twice_the_usual_price_the_group_starts_again(
    client: TestClient, db: Session
) -> None:
    _headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    check_prices(db, owner=owner, now=now)

    # $1.50 a lead now: under twice the usual $2.
    _window(db, owner=owner, account=account, now=now, spend=4_500, results=30)
    assert check_prices(db, owner=owner, now=now) == []

    assert _open(db) == []


def test_a_group_changed_in_the_last_72_hours_is_left_alone(
    client: TestClient, db: Session
) -> None:
    _headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    db.add(
        ActionLog(
            owner_id=owner.id,
            target_provider=PROVIDER,
            target_level="adset",
            target_external_id="s_1",
            action=ActionType.BUDGET_UP,
            status=ActionStatus.APPLIED,
            idempotency_key=uuid.uuid4().hex,
            created_at=now - timedelta(hours=20),
        )
    )
    db.commit()

    assert check_prices(db, owner=owner, now=now) == []


def test_without_history_of_its_own_the_niche_is_the_usual_price(
    client: TestClient, db: Session
) -> None:
    _headers, owner, account = _cabinet(client, db)
    now = utcnow()
    direction = BusinessCategory(
        key="cakes", label_uz="Tortlar", preset_key="restaurant"
    )
    db.add(direction)
    db.flush()
    db.add(
        Business(
            user_id=owner.id,
            name="Bahor",
            timezone="Asia/Tashkent",
            country_code="UZ",
            direction_id=direction.id,
        )
    )
    other = _neighbour(client, db, direction=direction, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)

    (row,) = check_prices(db, owner=owner, now=now)

    assert (row.baseline_source, row.cost_usual_minor) == ("niche_average", 200)
    assert other.currency == account.currency


def _neighbour(
    client: TestClient, db: Session, *, direction: BusinessCategory, now: datetime
) -> AdAccount:
    """Another owner of the same direction, three adverts at $2.00 a lead."""
    sign_up(client, email="qoshni@example.com")
    neighbour = db.scalar(select(User).where(User.email == "qoshni@example.com"))
    assert neighbour is not None
    connection = ProviderConnection(
        owner_id=neighbour.id,
        provider=PROVIDER,
        external_user_id="fb-2",
        token_encrypted=b"x",
        token_fingerprint="n",
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=neighbour.id,
        provider=PROVIDER,
        external_id="act_2",
        connection_id=connection.id,
        name="Qo'shni",
        currency="USD",
        timezone="Asia/Tashkent",
    )
    db.add(account)
    db.flush()
    campaign = Campaign(
        owner_id=neighbour.id,
        provider=PROVIDER,
        external_id="c_2",
        ad_account_id=account.id,
        name="Qo'shni",
        currency="USD",
    )
    db.add(campaign)
    db.flush()
    _old_group(db, neighbour.id, campaign, adset_id="s_n")
    db.add(
        Business(
            user_id=neighbour.id,
            name="Qo'shni",
            timezone="Asia/Tashkent",
            country_code="UZ",
            direction_id=direction.id,
        )
    )
    _history(
        db, owner_id=neighbour.id, account=account, now=now, adset_id="s_n", prefix="n"
    )
    db.commit()
    return account


def test_the_same_night_s_frequency_level_is_said_inside_the_price_rise(
    client: TestClient, db: Session
) -> None:
    from app.modules.notifications.services.announce_frequency import (
        morning_entries,
        morning_message,
    )

    _headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    check_prices(db, owner=owner, now=now)
    db.add(
        FrequencyAlert(
            owner_id=owner.id,
            provider=PROVIDER,
            ad_account_id=account.id,
            adset_external_id="s_1",
            name="Guruh",
            level="warning",
            frequency=253,
            currency="USD",
        )
    )
    db.commit()

    (entry,) = morning_entries(db, owner=owner, now=now)

    assert entry.price is not None and entry.frequency is not None
    text = morning_message([entry])
    assert "To'xtang, lid narxi oshib ketdi" in text
    assert "Frequency: 2,53 - kreativni almashtirish kerak." in text


@pytest.mark.parametrize("delivery", ["paused"])
def test_a_stopped_group_s_rise_closes(
    client: TestClient, db: Session, delivery: str
) -> None:
    _headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    check_prices(db, owner=owner, now=now)
    db.execute(
        update(AdSet).where(AdSet.external_id == "s_1").values(delivery=delivery)
    )
    db.commit()

    check_prices(db, owner=owner, now=now + timedelta(days=1))

    assert _open(db) == []


def test_a_paused_advert_is_no_delivery_problem_but_a_refused_one_is(
    client: TestClient, db: Session
) -> None:
    _headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    _day(
        db,
        owner_id=owner.id,
        account=account,
        adset_id="s_1",
        ad_id="a_2",
        day=_today(account, now) - timedelta(days=1),
        spend=300,
        results=1,
    )
    db.execute(update(Ad).where(Ad.external_id == "a_2").values(delivery="paused"))
    db.commit()

    (row,) = check_prices(db, owner=owner, now=now)
    assert row.ad_external_id == "a_1"

    db.execute(update(PriceAlert).values(closed_at=now))
    db.execute(update(Ad).where(Ad.external_id == "a_2").values(delivery="rejected"))
    db.commit()
    assert check_prices(db, owner=owner, now=now) == []


def test_an_advert_paused_on_its_own_closes_its_rise(
    client: TestClient, db: Session
) -> None:
    """Its group still runs, but the dear advert no longer does: no news."""
    _headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    # a_2, in the same group, keeps running at the usual price.
    for back in (1, 2, 3):
        _day(
            db,
            owner_id=owner.id,
            account=account,
            adset_id="s_1",
            ad_id="a_2",
            day=_today(account, now) - timedelta(days=back),
            spend=600,
            results=3,
        )
    db.commit()
    (row,) = check_prices(db, owner=owner, now=now)
    assert row.ad_external_id == "a_1"
    db.execute(update(Ad).where(Ad.external_id == "a_1").values(delivery="paused"))
    db.commit()

    check_prices(db, owner=owner, now=now + timedelta(hours=1))

    assert _open(db) == []


def test_watching_keeps_the_same_message_s_frequency_quiet_for_72_hours(
    client: TestClient, db: Session
) -> None:
    from app.modules.agent.selectors.frequency import alerts_to_show

    headers, owner, account = _cabinet(client, db)
    now = utcnow()
    _history(db, owner_id=owner.id, account=account, now=now)
    _window(db, owner=owner, account=account, now=now, spend=12_000, results=12)
    (row,) = check_prices(db, owner=owner, now=now)
    db.add(
        FrequencyAlert(
            owner_id=owner.id,
            provider=PROVIDER,
            ad_account_id=account.id,
            adset_external_id="s_1",
            name="Guruh",
            level="required",
            frequency=310,
            currency="USD",
        )
    )
    db.commit()

    watched = client.post(f"/api/v1/agent/price/{row.id}/watch", headers=headers)

    assert watched.status_code == 200, watched.text
    db.expire_all()
    later = utcnow() + timedelta(hours=48)
    assert alerts_to_show(db, owner=owner, now=later) == []
    assert alerts_to_show(db, owner=owner, now=later + timedelta(hours=25))
