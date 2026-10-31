"""One customer's adverts in the office: the list's figures and one advert whole."""

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.models import (
    AdCreative,
    AdPreview,
    CampaignLaunch,
    LaunchCreative,
    MediaAsset,
)
from app.modules.backoffice.constants import Role
from tests.pg.conftest import sign_up
from tests.pg.test_chat import _account
from tests.pg.test_chat import _mirror as _campaigns
from tests.pg.test_office_customers import URL, _staff

PROVIDER = "meta"
AI_TEXT = {
    "primary_text": "Tort buyurtma bering",
    "headline": "Bahorgi tort",
    "description": "",
}


def _launched(client: TestClient, db: Session) -> tuple[Any, CampaignLaunch, dict]:
    sign_up(client)
    owner, account, page = _account(db)
    _campaigns(db, owner, account, page)
    db.commit()
    launch = db.scalar(
        select(CampaignLaunch).where(CampaignLaunch.owner_id == owner.id)
    )
    assert launch is not None
    launch.currency = "USD"
    db.commit()
    _, headers = _staff(db, Role.SUPPORT, email="support@office.test")
    return owner, launch, headers


def _set_up(db: Session, owner: Any, launch: CampaignLaunch) -> None:
    """The customer took the AI's words, moved the placement, wrote the form."""
    launch.answers = {
        "goal_text": "Ko'proq buyurtma kerak",
        "lead_form_choice": "owner",
        "lead_form_questions": [{"kind": "custom", "label": "Qaysi tort?"}],
    }
    launch.targeting = {
        "geo_locations": {"cities": [{"key": "c1", "radius": 20}]},
        "age_min": 25,
        "age_max": 45,
        "genders": [2],
        "flexible_spec": [{"interests": [{"id": "1", "name": "Tortlar"}]}],
        "publisher_platforms": ["instagram"],
        "instagram_positions": ["story"],
    }
    launch.daily_budget_minor = 1000
    launch.currency = "USD"
    launch.draft = {
        "audience": {
            "ai": {"targeting_mode": "interests", "placement_mode": "automatic"},
            "chosen": {
                "targeting_mode": "interests",
                "placement_mode": "instagram",
                "geo": {
                    "places": [
                        {
                            "key": "c1",
                            "name": "Toshkent",
                            "kind": "city",
                            "country_code": "UZ",
                        }
                    ]
                },
            },
        },
        "interests": {
            "ai": [{"label": "Tortlar", "query": "t", "recommended": True}],
            "chosen": [{"label": "Tortlar", "query": "t", "external_id": "1"}],
        },
        "creative": {"ai": [AI_TEXT], "chosen": None},
        "form": {"ai": [{"kind": "phone", "label": "Telefon"}], "chosen": None},
        "sources": {"placement_mode": "owner", "audience_mode": "ai"},
    }
    db.add(
        LaunchCreative(
            owner_id=owner.id,
            launch_id=launch.id,
            position=0,
            primary_text=AI_TEXT["primary_text"],
            headline=AI_TEXT["headline"],
        )
    )
    db.add(
        LaunchCreative(
            owner_id=owner.id,
            launch_id=launch.id,
            position=1,
            primary_text="O'zim yozdim",
        )
    )
    db.commit()


def test_the_list_reads_every_figure_and_a_typed_stretch(
    client: TestClient, db: Session
) -> None:
    owner, _launch, headers = _launched(client, db)
    today = utcnow().date()

    body = client.get(f"{URL}/{owner.id}/ads?period=30", headers=headers).json()
    [row] = body["rows"]
    assert (row["impressions"], row["clicks"], row["link_clicks"]) == (7000, 280, 210)
    assert row["ctr_percent"] == "4.00" and row["cpc_minor"] == 12
    assert row["reach"] is None and row["campaign_name"] == "Bahor aksiyasi"
    [summary] = body["summary"]
    assert summary["spend_minor"] == 3500 and summary["lead_cost_minor"] == 3500

    typed = client.get(
        f"{URL}/{owner.id}/ads?period=range&since={today}&until={today}",
        headers=headers,
    ).json()
    assert typed["window"]["since"] == str(today) and typed["period"] == "range"
    assert [r["spend_minor"] for r in typed["rows"]] == [0]

    refused = client.get(f"{URL}/{owner.id}/ads?period=range", headers=headers).json()
    assert refused["window"]["refused"] and refused["period"] == "month"


def test_one_advert_reads_its_figures_over_the_window(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)

    url = f"{URL}/{owner.id}/ads/{launch.id}"
    week = client.get(f"{url}?period=7", headers=headers)
    assert week.status_code == 200, week.text
    body = week.json()
    figures = body["figures"]
    days = 6
    assert figures["sums"]["spend_minor"] == days * 500
    assert figures["sums"]["cpc_minor"] == 12
    assert figures["leads"] == 1 and figures["result"]["count"] == 1
    assert figures["reach_is_exact"] is False
    assert figures["lifetime_leads"]["total"] == 1
    assert body["bar"] == "day" and len(body["bars"]) == 7
    assert sum(row["sums"]["spend_minor"] for row in body["bars"]) == days * 500
    assert sum(row["leads"] for row in body["bars"]) == 1

    [group] = body["groups"]
    assert group["sums"]["spend_minor"] == days * 500
    assert group["audience"]["ages"] == "25-45 yosh"
    assert group["ads"][0]["external_id"] == "a_1" and group["ads"][0]["leads"] == 1
    assert body["campaign"]["name"] == "Bahor aksiyasi"
    assert body["live"]["status"] == "Yaratildi"
    assert body["live"]["ads"][0]["delivery_label"] == "Ishlayapti"
    assert group["delivery_label"] == "Ishlayapti"

    every = client.get(f"{url}?period=all", headers=headers).json()
    assert every["figures"]["sums"]["spend_minor"] == 3500
    assert every["bar"] == "day" and len(every["bars"]) == 8

    months = client.get(f"{url}?period=all&bar=month", headers=headers).json()
    assert months["bar"] == "month"
    assert sum(r["sums"]["spend_minor"] for r in months["bars"]) == 3500

    today = client.get(f"{url}?period=today", headers=headers).json()
    assert today["figures"]["sums"]["spend_minor"] == 0 and today["bars"] == []


def test_one_advert_says_who_decided_what(client: TestClient, db: Session) -> None:
    owner, launch, headers = _launched(client, db)
    _set_up(db, owner, launch)

    body = client.get(f"{URL}/{owner.id}/ads/{launch.id}", headers=headers).json()
    settings = body["settings"]
    assert settings["goal_text"] == "Ko'proq buyurtma kerak"
    assert settings["audience"]["places"] == ["Toshkent, 20 km atrofida"]
    assert settings["audience"]["ages"] == "25-45 yosh"
    assert settings["audience"]["genders"] == "Ayollar"
    assert settings["audience"]["interests"] == [["Tortlar"]]
    assert settings["audience"]["placements"] == ["Instagram: Stories"]

    by = {row["key"]: row for row in settings["decisions"]}
    assert by["audience"]["by"] == "ai"
    assert by["interests"]["by"] == "ai"
    assert by["placement"]["by"] == "owner"
    assert by["form"]["by"] == "owner"
    assert by["form"]["value"] == "Mijoz savollarni o'zi yozdi"
    assert [ad["words_by"] for ad in settings["ads"]] == ["ai", "owner"]


def test_a_form_the_ai_picked_says_so(client: TestClient, db: Session) -> None:
    owner, launch, headers = _launched(client, db)
    launch.lead_form_external_id = "f_1"
    launch.draft = {"sources": {"lead_form": "ai"}}
    db.commit()

    body = client.get(f"{URL}/{owner.id}/ads/{launch.id}", headers=headers).json()
    [decision] = [r for r in body["settings"]["decisions"] if r["key"] == "form"]
    assert decision["value"] == "AI tayyor formani tanladi"
    [form] = body["live"]["forms"]
    assert form["is_synced"] is True and form["name"] == "Buyurtma"


def test_the_post_opens_where_it_lives(client: TestClient, db: Session) -> None:
    owner, launch, headers = _launched(client, db)
    creative = db.scalar(select(AdCreative).where(AdCreative.external_id == "cr_1"))
    assert creative is not None

    url = f"{URL}/{owner.id}/ads/{launch.id}"
    assert client.get(url, headers=headers).json()["live"]["ads"][0]["post"] is None

    creative.post_external_id = "page_1_777"
    db.commit()
    [ad] = client.get(url, headers=headers).json()["live"]["ads"]
    assert ad["post"]["url"] == "https://www.facebook.com/page_1_777"
    assert ad["post"]["kind_label"] == "Facebook posti"

    creative.post_external_id = "1788"
    db.add(
        MediaAsset(
            owner_id=owner.id,
            provider=PROVIDER,
            kind="ig_image",
            external_id="1788",
            name="Instagramdagi post",
            thumbnail_url="https://cdn.test/1.jpg",
            permalink_url="https://www.instagram.com/p/abc/",
        )
    )
    db.commit()
    [ad] = client.get(url, headers=headers).json()["live"]["ads"]
    assert ad["post"]["url"] == "https://www.instagram.com/p/abc/"
    assert ad["post"]["text"] == "Instagramdagi post"
    assert ad["post"]["kind_label"] == "Instagram rasmi"


def test_a_launch_that_made_no_campaign_is_read_without_figures(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    launch.created_refs = {}
    launch.error_message = "Meta rad etdi"
    db.commit()

    body = client.get(f"{URL}/{owner.id}/ads/{launch.id}", headers=headers).json()
    assert body["row"] is None and body["figures"] is None
    assert body["live"]["error"] == "Meta rad etdi"


def test_another_customers_launch_is_not_read(client: TestClient, db: Session) -> None:
    owner, launch, headers = _launched(client, db)
    other, _ = _staff(db, Role.SUPPORT, email="other@office.test")

    for tail in ("", "/preview/a_1"):
        answer = client.get(f"{URL}/{other.id}/ads/{launch.id}{tail}", headers=headers)
        assert answer.status_code == 404
    sales, sales_headers = _staff(db, Role.SALES, email="sales@office.test")
    assert sales.id
    answer = client.get(f"{URL}/{owner.id}/ads/{launch.id}", headers=sales_headers)
    assert answer.status_code == 404


def test_the_preview_is_fetched_once_and_then_drawn(
    client: TestClient, db: Session
) -> None:
    owner, launch, headers = _launched(client, db)
    url = f"{URL}/{owner.id}/ads/{launch.id}/preview"

    assert client.get(f"{url}/nope", headers=headers).status_code == 404
    with patch("app.modules.ads.tasks.fetch_preview_task.delay") as fetch:
        first = client.get(f"{url}/a_1", headers=headers).json()
        second = client.get(f"{url}/a_1?tries=1", headers=headers).json()
    assert fetch.call_count == 1
    assert first["polling"] is True and first["tries"] == 1
    assert second["polling"] is True and second["src"] == ""

    account = launch.ad_account_id
    db.add(
        AdPreview(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id="a_1",
            ad_account_id=account,
            ad_format="MOBILE_FEED_STANDARD",
            src="https://www.facebook.com/ads/api/preview_iframe.php?d=1",
            width=320,
            height=480,
            fetched_at=utcnow(),
        )
    )
    db.commit()
    drawn = client.get(f"{url}/a_1?tries=2", headers=headers).json()
    assert drawn["src"].endswith("d=1") and drawn["polling"] is False
    assert drawn["gave_up"] is False
