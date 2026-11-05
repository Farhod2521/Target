"""The expert table: a cell per metric, computed in one place, and the columns."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.contract.expert import PRESETS
from app.modules.metrics.models import MetricsDaily
from tests.pg.test_campaigns_v2 import IMPRESSIONS, LINK_CLICKS, REACH, SPEND, _figures

EXPERT = "/api/v2/campaigns/expert"


def _table(client: TestClient, headers: dict[str, str]) -> Any:
    answer = client.get(f"{EXPERT}?period=7d", headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()


def _video_ad(db: Session) -> None:
    ad = db.scalar(select(MetricsDaily).where(MetricsDaily.level == "ad"))
    assert ad is not None
    ad.video_plays = 20_000
    ad.video_views_3s = 16_000
    ad.video_thruplays = 4_000
    ad.quality_ranking = "below_average_20"
    ad.engagement_rate_ranking = "average"
    ad.conversion_rate_ranking = "above_average"
    db.commit()


def test_every_level_has_its_cells_and_none_of_the_old_figures(
    client: TestClient, db: Session
) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")

    body = _table(client, headers)

    for rows in (body["campaigns"], body["adsets"], body["ads"]):
        row = rows[0]
        cells = row["cells"]
        assert cells["spend"] == {"value": SPEND, "missing": None}
        assert cells["impressions"]["value"] == IMPRESSIONS
        assert cells["link_clicks"]["value"] == LINK_CLICKS
        assert cells["reach"]["value"] == REACH
        assert cells["ctr"]["value"] == 8.44
        assert cells["cpm"]["value"] == 136
        assert cells["cpc"]["value"] == 2
        assert cells["frequency"]["value"] == 1.62
        assert row["outcome"] == "click"
        assert row["currency"] == "USD"
        for gone in ("results", "unitCost", "spent", "clicks"):
            assert gone not in row


def test_only_an_ad_has_the_video_rates_and_the_rankings(
    client: TestClient, db: Session
) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")
    _video_ad(db)

    body = _table(client, headers)

    ad = body["ads"][0]["cells"]
    assert ad["hook_rate"]["value"] == 24.62
    assert ad["hold_rate"]["value"] == 25.0
    assert ad["quality_ranking"]["value"] == "below_average_20"
    assert ad["conversion_rate_ranking"]["value"] == "above_average"
    for level in ("campaigns", "adsets"):
        assert "hook_rate" not in body[level][0]["cells"]
        assert "quality_ranking" not in body[level][0]["cells"]


def test_without_a_crm_the_crm_cells_say_so(client: TestClient, db: Session) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")

    cells = _table(client, headers)["campaigns"][0]["cells"]

    for key in ("qualified", "qualified_share", "cpql", "purchases_crm"):
        assert cells[key] == {"value": None, "missing": "no_crm"}, key


def test_each_level_has_a_total_from_its_sums(client: TestClient, db: Session) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")

    body = _table(client, headers)

    total = body["totals"]["campaigns"]
    assert total["count"] == 1
    assert total["currency"] == "USD"
    assert total["cells"]["spend"]["value"] == SPEND
    assert total["cells"]["ctr"]["value"] == 8.44
    assert body["attribution"] == {"asked": "7d_click_1d_view", "differs": False}
    assert body["syncedAt"] is not None


def test_the_columns_are_the_catalogue_and_the_choice_is_kept(
    client: TestClient, db: Session
) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")

    first = client.get(f"{EXPERT}/columns", headers=headers).json()
    assert first["chosen"] == list(PRESETS["general"])
    campaign = [column["key"] for column in first["levels"]["campaigns"]]
    ad = [column["key"] for column in first["levels"]["ads"]]
    assert "hook_rate" in ad and "hook_rate" not in campaign
    assert first["missing"]["no_crm"] == "CRM yoqilmagan"
    assert {preset["key"] for preset in first["presets"]} == {
        "general",
        "video",
        "quality",
        "sales",
    }

    saved = client.put(
        f"{EXPERT}/columns",
        headers=headers,
        json={"chosen": ["cpm", "spend", "nonsense", "cpm"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["chosen"] == ["cpm", "spend"]
    again = client.get(f"{EXPERT}/columns", headers=headers).json()
    assert again["chosen"] == ["cpm", "spend"]


def test_the_screens_version_answers_the_same(client: TestClient, db: Session) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")

    old = client.get("/api/v1/campaigns/expert?period=7d", headers=headers)
    columns = client.get("/api/v1/campaigns/expert/columns", headers=headers)

    assert old.status_code == 200, old.text
    assert old.json()["totals"] == _table(client, headers)["totals"]
    assert columns.status_code == 200, columns.text


def test_ticked_campaigns_narrow_the_levels_under_them(
    client: TestClient, db: Session
) -> None:
    headers, _, _ = _figures(client, db, goal="LINK_CLICKS")

    other = client.get(f"{EXPERT}?period=7d&campaigns=c_other", headers=headers).json()
    own = client.get(f"{EXPERT}?period=7d&campaigns=c_1&adsets=s_1", headers=headers).json()

    assert [row["id"] for row in other["campaigns"]] == ["c_1"]
    assert other["adsets"] == [] and other["ads"] == []
    assert other["totals"]["adsets"]["count"] == 0
    assert [row["id"] for row in own["ads"]] == ["a_1"]
    assert own["totals"]["ads"]["cells"]["spend"]["value"] == SPEND
