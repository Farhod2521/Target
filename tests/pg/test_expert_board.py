"""The expert dashboard: every block from the catalogue, nothing computed twice."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.metrics.models import MetricsDaily
from tests.pg.test_campaigns_v2 import IMPRESSIONS, LINK_CLICKS, REACH, SPEND, _figures

BOARD = "/api/v1/metrics/expert"


def _board(client: TestClient, headers: dict[str, str]) -> Any:
    answer = client.get(f"{BOARD}?period=7", headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_headline_is_the_catalogues_with_the_range_before(
    client: TestClient, db: Session
) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")

    body = _board(client, headers)

    headline = {row["key"]: row for row in body["headline"]}
    assert list(headline) == [
        "spend",
        "results",
        "cost_per_result",
        "cpm",
        "ctr",
        "cpc",
        "frequency",
        "reach",
    ]
    assert headline["spend"]["now"] == {"value": SPEND, "missing": None}
    assert headline["ctr"]["now"]["value"] == 8.44
    assert headline["reach"]["now"]["value"] == REACH
    # What the advertising sold stands in the sales block, not here.
    assert "roas" not in headline and "cpql" not in headline
    assert headline["spend"]["before"]["value"] == 0
    assert set(headline["spend"]["change"]) == {"percent", "direction", "is_good"}
    assert body["range"]["days"] == 7
    assert body["before"] is not None


def test_the_days_and_the_funnel(client: TestClient, db: Session) -> None:
    headers, _, today = _figures(client, db, goal="LINK_CLICKS")

    body = _board(client, headers)

    days = body["series"]["days"]
    assert len(days) == 7
    last = days[-1]
    assert last["day"] == today.isoformat()
    assert last["cells"]["spend"]["value"] == SPEND
    assert "reach" not in body["series"]["keys"]
    funnel = {step["key"]: step for step in body["funnel"]}
    assert funnel["impressions"]["count"]["value"] == IMPRESSIONS
    assert funnel["link_clicks"]["count"]["value"] == LINK_CLICKS
    assert funnel["link_clicks"]["rate"]["value"] == 8.44
    assert funnel["qualified"]["count"]["missing"] == "no_crm"


def test_each_goal_apart_and_the_troubled_adverts(
    client: TestClient, db: Session
) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")
    ad = db.scalar(select(MetricsDaily).where(MetricsDaily.level == "ad"))
    assert ad is not None
    ad.video_plays = 20_000
    ad.video_views_3s = 6_000
    ad.video_thruplays = 300
    db.commit()

    body = _board(client, headers)

    assert [goal["outcome"] for goal in body["goals"]] == ["click"]
    assert body["goals"][0]["cells"]["spend"]["value"] == SPEND
    (troubled,) = body["troubled"]
    assert troubled["id"] == "a_1"
    assert {one["key"] for one in troubled["problems"]} == {"hook_rate", "hold_rate"}
    assert "segments" in body and "lead_quality" in body


def test_campaigns_built_in_ads_manager_are_counted_too(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    """The plain dashboard counts the campaigns built here; the expert one,
    like the expert table, every campaign of the page."""
    from app.modules.ads import selectors
    from app.modules.ads.selectors.pages import PageAdvertising

    headers, campaign, _ = _figures(client, db, goal="LINK_CLICKS")
    real = selectors.page_advertising(db, owner=campaign.owner)
    elsewhere = PageAdvertising(
        page=real.page,
        sole=real.sole,
        elsewhere=frozenset({"c_1"}),
        accounts=real.accounts,
    )
    monkeypatch.setattr(selectors, "page_advertising", lambda *_a, **_k: elsewhere)

    body = _board(client, headers)

    headline = {row["key"]: row for row in body["headline"]}
    assert headline["spend"]["now"]["value"] == SPEND


def test_a_campaign_whose_own_row_is_gone_still_counts_its_days(
    client: TestClient, db: Session, monkeypatch: Any
) -> None:
    """The plain dashboard sums a campaign's days whether or not its row is
    kept; the expert one must agree with it on the spend."""
    from app.common.db import utcnow
    from app.modules.ads import selectors
    from app.modules.ads.selectors.pages import PageAdvertising
    from app.modules.metrics.models import MetricsDaily

    headers, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    db.add(
        MetricsDaily(
            owner_id=campaign.owner_id,
            ad_account_id=campaign.ad_account_id,
            provider="meta",
            external_id="s_gone",
            level="adset",
            campaign_external_id="c_gone",
            adset_external_id="s_gone",
            date=today,
            spend_minor=500,
            currency="USD",
            impressions=1000,
            synced_at=utcnow(),
        )
    )
    db.commit()
    real = selectors.page_advertising(db, owner=campaign.owner)
    both = PageAdvertising(
        page=real.page,
        sole=real.sole,
        elsewhere=frozenset({"c_1", "c_gone"}),
        accounts=real.accounts,
    )
    monkeypatch.setattr(selectors, "page_advertising", lambda *_a, **_k: both)

    body = _board(client, headers)

    headline = {row["key"]: row for row in body["headline"]}
    assert headline["spend"]["now"]["value"] == SPEND + 500
    assert body["series"]["days"][-1]["cells"]["spend"]["value"] == SPEND + 500


def test_the_audience_cuts_cover_the_range_on_screen(
    client: TestClient, db: Session
) -> None:
    from datetime import timedelta

    from app.common.db import utcnow
    from app.modules.metrics.constants import EVERY_ACCOUNT, BreakdownKind
    from app.modules.metrics.models import MetricsBreakdown
    from app.modules.metrics.selectors.dashboard import page_segments
    from app.modules.metrics.selectors.scope import page_campaigns

    _, campaign, today = _figures(client, db, goal="LEAD_GENERATION")
    for back, spend in ((0, 1_000), (20, 9_000)):
        db.add(
            MetricsBreakdown(
                owner_id=campaign.owner_id,
                ad_account_id=campaign.ad_account_id,
                provider="meta",
                external_id="s_1",
                level="adset",
                campaign_external_id="c_1",
                adset_external_id="s_1",
                date=today - timedelta(days=back),
                breakdown_kind=str(BreakdownKind.AGE_GENDER),
                breakdown_value="25-34|female",
                spend_minor=spend,
                currency="USD",
                impressions=5_000,
                leads_reported=20,
                synced_at=utcnow(),
            )
        )
    db.commit()
    page = page_campaigns(db, owner=campaign.owner, every=True)

    def spent(days: int) -> tuple[int, int]:
        blocks, spans = page_segments(
            db,
            owner=campaign.owner,
            since=today - timedelta(days=days - 1),
            until=today,
            currency="USD",
            rows_of=EVERY_ACCOUNT,
            scope=lambda model: model.campaign_external_id == "c_1",
            account=page.home,
            campaign_ids=frozenset({"c_1"}),
        )
        age = next(b for b in blocks if b.key == str(BreakdownKind.AGE_GENDER))
        rows = (*age.ranked, *age.barren)
        return sum(row.spend_minor for row in rows), spans[age.key]

    # Seven days hold the one day's $10; thirty hold both days' $100.
    assert spent(7) == (1_000, 7)
    assert spent(30) == (10_000, 21)
