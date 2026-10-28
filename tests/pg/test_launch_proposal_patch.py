"""The review screen's save as a patch: a field left out keeps what it held."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    ATTRIBUTION,
    FREQUENCY_CAP,
    DraftSection,
    MediaKind,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from tests.pg.test_launch_api import _ready


def _reviewed(
    client: TestClient, db: Session, auth: dict[str, str], user_id: object
) -> CampaignLaunch:
    """A traffic launch with one advert, its proposal drawn."""
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    plan = client.get(f"/api/v1/launch/{launch_id}/plan?goal=traffic", headers=auth)
    saved = client.post(
        f"/api/v1/launch/{launch_id}/plan",
        json={
            "goal": "traffic",
            "daily_budget": plan.json()["initial"]["daily_budget"] or "10",
            "link_url": "bahor.example",
            "start_day": "tomorrow",
        },
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    launch = db.get(CampaignLaunch, saved.json()["id"])
    assert launch is not None
    asset = MediaAsset(
        owner_id=user_id,
        ad_account_id=launch.ad_account_id,
        provider=launch.provider,
        kind=MediaKind.IMAGE,
        external_id="hash_1",
        name="osh.jpg",
        width=1080,
        height=1080,
    )
    db.add(asset)
    db.commit()
    went = client.post(
        f"/api/v1/launch/{launch_id}/media",
        json={
            "asset_ids": [str(asset.id)],
            "text": {"mode": "shared", "shared": "Yangi osh, chegirma bilan"},
        },
        headers=auth,
    )
    assert went.status_code == 200, went.text
    db.refresh(launch)
    draft = draft_field.empty_draft()
    draft_field.choose(
        draft,
        DraftSection.AUDIENCE,
        {"age_min": 25, "age_max": 45, "genders": [2], "radius_km": None},
    )
    launch.draft = draft
    launch.status = "ready"
    launch.targeting = {"geo_locations": {"countries": ["UZ"]}}
    assert launch.start_date is not None
    launch.end_date = launch.start_date + timedelta(days=10)
    launch.answers = {
        **launch.answers,
        ATTRIBUTION: "click_7",
        FREQUENCY_CAP: [3, 7],
        "text_mode": "each",
    }
    db.commit()
    return launch


def _variant(db: Session, launch: CampaignLaunch) -> LaunchCreative:
    db.expire_all()
    found = db.scalar(
        select(LaunchCreative).where(LaunchCreative.launch_id == launch.id)
    )
    assert found is not None
    return found


def test_a_field_left_out_keeps_what_the_launch_holds(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)
    edit = f"/api/v1/launch/{launch.id}/edit"
    end_date = launch.end_date

    kept = client.post(edit, json={"advanced": {}}, headers=auth)
    assert kept.status_code == 200, kept.text
    db.expire_all()
    db.refresh(launch)
    assert launch.end_date == end_date
    assert launch.answers[ATTRIBUTION] == "click_7"
    assert launch.answers[FREQUENCY_CAP] == [3, 7]

    cleared = client.post(edit, json={"advanced": {"cap_times": None}}, headers=auth)
    assert cleared.status_code == 200, cleared.text
    db.refresh(launch)
    assert not launch.answers[FREQUENCY_CAP]
    assert launch.end_date == end_date

    aged = client.post(edit, json={"audience": {"age_min": 30}}, headers=auth)
    assert aged.status_code == 200, aged.text
    db.refresh(launch)
    audience = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    assert (audience["age_min"], audience["age_max"]) == (30, 45)
    assert audience["genders"] == [2]

    variant = _variant(db, launch)
    variant.primary_text = "Yangi osh, chegirma bilan"
    variant.headline = "Eski sarlavha"
    db.commit()
    renamed = client.post(
        edit,
        json={"creatives": [{"position": variant.position, "description": "Tavsif"}]},
        headers=auth,
    )
    assert renamed.status_code == 200, renamed.text
    variant = _variant(db, launch)
    assert variant.primary_text == "Yangi osh, chegirma bilan"
    assert (variant.headline, variant.description) == ("Eski sarlavha", "Tavsif")

    emptied = client.post(
        edit,
        json={"creatives": [{"position": variant.position, "headline": None}]},
        headers=auth,
    )
    assert emptied.status_code == 200, emptied.text
    variant = _variant(db, launch)
    assert (variant.headline, variant.description) == ("", "Tavsif")


def test_a_section_the_goal_does_not_draw_is_refused(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)

    refused = client.post(
        f"/api/v1/launch/{launch.id}/edit", json={"form": {}}, headers=auth
    )
    assert refused.status_code == 422, refused.text
    assert "form" in refused.json()["problems"]


def test_the_text_mode_left_out_is_kept(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch = _reviewed(client, db, auth, user.id)

    saved = client.post(
        f"/api/v1/launch/{launch.id}/media/text",
        json={"briefs": {str(_variant(db, launch).id): "Har biriga o'z matni"}},
        headers=auth,
    )
    assert saved.status_code == 204, saved.text
    db.expire_all()
    db.refresh(launch)
    assert launch.answers["text_mode"] == "each"
