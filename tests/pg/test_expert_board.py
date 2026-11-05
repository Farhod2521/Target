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
        "cpql",
        "roas",
        "cpm",
        "ctr",
        "cpc",
        "frequency",
        "reach",
    ]
    assert headline["spend"]["now"] == {"value": SPEND, "missing": None}
    assert headline["ctr"]["now"]["value"] == 8.44
    assert headline["reach"]["now"]["value"] == REACH
    assert headline["cpql"]["now"]["missing"] == "no_crm"
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
