"""Metrics against PostgreSQL: the upsert, the read-back selectors, and the scope."""

from datetime import timedelta

from adskit.dto import MetricsDTO
from adskit.refs import ExternalRef, ProviderName
from metaads import PROVIDER
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.metrics import selectors, services
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from tests.pg.test_cabinet_flows import _cabinet


def _row(day, *, spend: int, leads: int = 0) -> MetricsDTO:  # type: ignore[no-untyped-def]
    return MetricsDTO(
        ref=ExternalRef(provider=ProviderName(PROVIDER), level="adset", id="s_1"),
        day=day,
        campaign_external_id="c_1",
        adset_external_id="s_1",
        spend_minor=spend,
        currency="USD",
        impressions=100,
        leads_reported=leads,
    )


def test_store_restate_and_read_back(db: Session) -> None:
    owner = User(email="m@example.com", full_name="M", password="!", date_joined=utcnow())
    db.add(owner)
    db.commit()
    account, _page = _cabinet(db, owner)
    account.is_active = True
    account.is_current = True
    db.commit()
    today = utcnow().date()
    yesterday = today - timedelta(days=1)

    written = services.store_metrics(
        db,
        ad_account=account,
        rows=[_row(yesterday, spend=500, leads=2), _row(today, spend=300)],
        now=utcnow(),
        level=MetricLevel.ADSET,
    )
    assert written == 2
    services.store_metrics(
        db,
        ad_account=account,
        rows=[_row(today, spend=900, leads=1)],
        now=utcnow(),
        level=MetricLevel.ADSET,
    )
    assert db.scalar(select(func.count(MetricsDaily.id))) == 2
    assert db.scalar(select(func.sum(MetricsDaily.spend_minor))) == 1400

    assert selectors.newest_metrics_date(db, ad_account=account) == today
    assert selectors.has_spent(db, owner=owner, adset_id="s_1")
    assert selectors.campaign_has_run(db, owner=owner, campaign_id="c_1")
    assert selectors.last_synced_at(db, owner=owner) is not None

    sums = selectors.facts_by_campaign(db, owner=owner, since=yesterday, until=today)
    assert sums["c_1"].spend_minor == 1400 and sums["c_1"].leads_reported == 3
    only = selectors.facts_by_campaign(
        db, owner=owner, since=yesterday, until=today, scope=selectors.campaigns_scope({"x"})
    )
    assert only == {}

    days = selectors.daily_facts(
        db, owner=owner, since=yesterday, until=today, tzinfo=account.tzinfo()
    )
    assert [int(day.spend_minor) for day in days] == [500, 900]
    assert selectors.short_pages_today(db, owner=owner, account=account, now=utcnow()) == set()


def test_lead_sources_endpoint(client) -> None:  # type: ignore[no-untyped-def]
    from tests.pg.conftest import sign_up

    headers = sign_up(client)
    answer = client.get("/api/v1/leads/sources?days=7", headers=headers)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["days"] == 7 and body["report"]["rows"] == []
