"""``/api/v2/campaigns``: the figures version 1 loses, beside version 1 unchanged."""

from datetime import date, timedelta
from typing import Any

import pytest
from adskit.dto import PeopleCountDTO
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.exceptions import SyncFailed
from app.modules.ads.models import AdSet
from app.modules.metrics.models import MetricsDaily, PeopleCount
from app.modules.metrics.services import sync
from app.modules.metrics.services.sync import extra_people_ranges, people_ranges
from tests.pg.test_campaigns_contract import _cabinet_with_figures

SPEND = 8870
IMPRESSIONS = 64987
REACH = 40000
LINK_CLICKS = 5484
EVENTS = 200


def _figures(
    client: TestClient,
    db: Session,
    *,
    goal: str,
    promoted: dict[str, str] | None = None,
) -> tuple[dict[str, str], Any, date]:
    headers, campaign = _cabinet_with_figures(client, db)
    group = db.scalar(select(AdSet).where(AdSet.campaign_id == campaign.id))
    assert group is not None
    group.optimization_goal_raw = goal
    group.promoted_object_raw = promoted
    campaign.objective_raw = "OUTCOME_LEADS"
    account = campaign.ad_account
    today = utcnow().astimezone(account.tzinfo()).date()
    db.query(MetricsDaily).delete()
    for level, external_id in (("campaign", "c_1"), ("adset", "s_1"), ("ad", "a_1")):
        ids = {
            "owner_id": campaign.owner_id,
            "ad_account_id": account.id,
            "provider": PROVIDER,
            "external_id": external_id,
            "level": level,
            "campaign_external_id": "c_1",
            "adset_external_id": "s_1",
            "synced_at": utcnow(),
        }
        db.add(
            MetricsDaily(
                **ids,
                date=today,
                spend_minor=SPEND,
                currency="USD",
                impressions=IMPRESSIONS,
                reach=REACH,
                clicks=7000,
                inline_link_clicks=LINK_CLICKS,
                results_reported=EVENTS,
            )
        )
        db.add(
            PeopleCount(
                **ids,
                since=today - timedelta(days=6),
                until=today,
                reach=REACH,
                recallers=0,
            )
        )
    db.commit()
    return headers, campaign, today


def _manager(client: TestClient, headers: dict[str, str], query: str) -> Any:
    answer = client.get(f"/api/v2/campaigns/manager?{query}", headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_every_level_carries_its_link_clicks(client: TestClient, db: Session) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")

    body = _manager(client, headers, "period=7d")

    for rows in (body["campaigns"], body["adsets"], body["ads"]):
        assert rows[0]["clicks"] == LINK_CLICKS
        assert rows[0]["reach"] == REACH
        assert rows[0]["impressions"] == IMPRESSIONS
        assert rows[0]["kind"] == "click"


def test_days_nobody_counted_are_unknown_not_nought(
    client: TestClient, db: Session
) -> None:
    headers, _, today = _figures(client, db, goal="LINK_CLICKS")
    since = today - timedelta(days=13)

    body = _manager(client, headers, f"period=custom&since={since}&until={today}")

    assert body["campaigns"][0]["reach"] is None
    assert body["ads"][0]["clicks"] == LINK_CLICKS


def test_an_event_on_the_site_is_counted_and_named(
    client: TestClient, db: Session
) -> None:
    headers, campaign, _ = _figures(
        client,
        db,
        goal="OFFSITE_CONVERSIONS",
        promoted={"custom_event_type": "COMPLETE_REGISTRATION"},
    )

    body = _manager(client, headers, "period=7d")
    listed = client.get("/api/v2/campaigns?period=7d", headers=headers).json()
    tree = client.get(
        f"/api/v2/campaigns/{campaign.id}/tree?period=7d", headers=headers
    ).json()

    for rows in (body["campaigns"], body["adsets"], body["ads"]):
        assert rows[0]["kind"] == "conversion"
        assert rows[0]["resultLabel"] == "Ro'yxatdan o'tishlar"
        assert rows[0]["results"] == EVENTS
        assert rows[0]["unitCost"]["minor"] == 44
    row = listed["campaigns"][0]
    assert row["kind"] == "conversion" and row["metrics"]["results"] == EVENTS
    assert tree["groups"][0]["ads"][0]["results"] == EVENTS


def test_a_profile_visit_goal_counts_its_visits(
    client: TestClient, db: Session
) -> None:
    headers, _, _ = _figures(client, db, goal="VISIT_INSTAGRAM_PROFILE")

    row = _manager(client, headers, "period=7d")["campaigns"][0]

    assert row["kind"] == "profile" and row["results"] == EVENTS
    assert row["unitCost"]["minor"] == 44


def test_a_goal_with_no_figure_says_so(client: TestClient, db: Session) -> None:
    headers, _, _ = _figures(client, db, goal="THRUPLAY")

    row = _manager(client, headers, "period=7d")["campaigns"][0]

    assert row["kind"] == "other" and row["results"] == 0
    assert row["unitCost"] is None


def test_the_tree_follows_the_period_it_is_asked(
    client: TestClient, db: Session
) -> None:
    headers, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    row = db.scalar(select(MetricsDaily).where(MetricsDaily.level == "ad"))
    assert row is not None
    row.date = today - timedelta(days=10)
    db.commit()

    url = f"/api/v2/campaigns/{campaign.id}/tree"
    week = client.get(f"{url}?period=7d", headers=headers).json()
    since = today - timedelta(days=13)
    fortnight = client.get(
        f"{url}?period=custom&since={since}&until={today}", headers=headers
    ).json()

    assert week["groups"][0]["ads"][0]["spent"] is None
    assert fortnight["groups"][0]["ads"][0]["spent"]["minor"] == SPEND


def test_version_one_answers_as_it_did(client: TestClient, db: Session) -> None:
    headers, campaign, today = _figures(
        client,
        db,
        goal="OFFSITE_CONVERSIONS",
        promoted={"custom_event_type": "COMPLETE_REGISTRATION"},
    )
    since = today - timedelta(days=13)

    row = client.get(
        f"/api/v1/campaigns/manager?period=custom&since={since}&until={today}",
        headers=headers,
    ).json()["campaigns"][0]
    tree = client.get(f"/api/v1/campaigns/{campaign.id}/tree", headers=headers)

    assert row["kind"] == "click" and row["results"] == 0
    assert row["clicks"] == 0 and row["reach"] == 0
    assert "resultLabel" not in row
    assert tree.status_code == 200


def test_the_extra_ranges_add_only_what_the_periods_lack() -> None:
    saturday = date(2026, 10, 31)

    extra = extra_people_ranges(saturday)

    assert (date(2026, 10, 18), saturday) in extra
    assert (date(2026, 10, 4), saturday) in extra
    assert (date(2026, 10, 26), saturday) in extra
    assert (date(2026, 10, 19), date(2026, 10, 25)) in extra
    assert (date(2026, 10, 1), saturday) in extra
    assert (date(2026, 9, 1), date(2026, 9, 30)) in extra
    assert not set(extra) & set(people_ranges(saturday))
    assert len(extra) == len(set(extra))


def test_a_refused_extra_range_keeps_the_periods(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    account = campaign.ad_account
    base = people_ranges(today)

    def read(
        _db: Session, _account: Any, *, ranges: list[Any], level: str
    ) -> list[PeopleCountDTO]:
        if ranges != base:
            raise SyncFailed(cause="provider_error")
        return [
            PeopleCountDTO(
                ref=ExternalRef(provider=PROVIDER, level=level, id="c_1"),
                since=ranges[0][0],
                until=ranges[0][1],
                campaign_external_id="c_1",
                reach=REACH,
            )
        ]

    monkeypatch.setattr(sync, "_read_people", read)

    written = sync.sync_people(db, ad_account=account, today=today)

    assert written == 3
    assert db.scalar(select(PeopleCount).where(PeopleCount.since == today))
