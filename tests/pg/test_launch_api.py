"""The new-advert wizard over HTTP: open, plan, pictures, review, refusals."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import MediaKind
from app.modules.ads.launch_schemas import ReviewOut, ReviewPollOut
from app.modules.ads.models import CampaignLaunch, MediaAsset
from app.modules.billing.services import start_trial
from app.modules.billing.services.grants import complete_setup
from app.modules.businesses.models import BusinessCategory
from tests.pg.conftest import sign_up
from tests.pg.test_cabinet_flows import _cabinet


def _ready(client: TestClient, db: Session) -> tuple[dict[str, str], User]:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    start_trial(db, user=user, now=utcnow())
    db.add(
        BusinessCategory(
            key="restaurant",
            label_uz="Restoran",
            label_ru="Ресторан",
            label_en="Restaurant",
            preset_key="restaurant",
            position=0,
        )
    )
    db.commit()
    account, _page = _cabinet(db, user)
    account.is_active = account.is_current = True
    db.commit()
    chosen = client.post(
        "/api/v1/connections/meta/page", json={"external_id": "page_1"}, headers=auth
    )
    assert chosen.status_code == 200, chosen.text
    saved = client.put(
        "/api/v1/business",
        json={
            "name": "Bahor",
            "category": "restaurant",
            "country_code": "UZ",
            "timezone": "Asia/Tashkent",
            "website": "https://bahor.example",
        },
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    complete_setup(db, owner=user, now=utcnow())
    db.commit()
    return auth, user


def test_the_wizard_from_plan_to_review(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)

    opened = client.post("/api/v1/launch", headers=auth)
    assert opened.status_code == 201, opened.text
    launch_id = opened.json()["id"]
    assert opened.json()["resume"] == "plan"
    assert client.post("/api/v1/launch", headers=auth).json()["id"] == launch_id

    plan = client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth)
    assert plan.status_code == 200, plan.text
    goals = [item["goal"] for item in plan.json()["goals"]]
    assert goals

    empty = client.post(f"/api/v1/launch/{launch_id}/plan", json={}, headers=auth)
    assert empty.status_code == 422
    assert empty.json()["code"] == "invalid_input"
    assert "goal" in empty.json()["problems"]

    goal = "traffic" if "traffic" in goals else goals[0]
    fields = client.get(
        f"/api/v1/launch/{launch_id}/plan?goal={goal}", headers=auth
    ).json()
    budget = fields["initial"]["daily_budget"] or "10"
    body = {
        "goal": goal,
        "daily_budget": budget,
        "link_url": "bahor.example",
        "phone_number": "+998901234567",
        "welcome_text": "Salom!",
        "start_day": "tomorrow",
    }
    saved = client.post(f"/api/v1/launch/{launch_id}/plan", json=body, headers=auth)
    assert saved.status_code == 200, saved.text
    assert saved.json()["next"] == "media"
    launch = db.get(CampaignLaunch, saved.json()["id"])
    db.refresh(launch)
    assert launch is not None and launch.answers["goal"] == goal
    assert launch.daily_budget_minor and launch.start_date is not None

    tiny = client.post(
        f"/api/v1/launch/{launch_id}/plan",
        json=body | {"daily_budget": "0.001"},
        headers=auth,
    )
    assert tiny.status_code == 422 and "daily_budget" in tiny.json()["problems"]

    nothing = client.post(f"/api/v1/launch/{launch_id}/media", json={}, headers=auth)
    assert nothing.status_code == 422

    asset = MediaAsset(
        owner_id=user.id,
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
    step = client.get(f"/api/v1/launch/{launch_id}/media", headers=auth)
    assert step.status_code == 200, step.text
    assert step.json()["count"]["chosen"] == 0

    went = client.post(
        f"/api/v1/launch/{launch_id}/media",
        json={
            "asset_ids": [str(asset.id)],
            "text": {"mode": "shared", "shared": "Yangi osh, chegirma bilan"},
        },
        headers=auth,
    )
    assert went.status_code == 200, went.text
    assert went.json()["next"] == "review"
    assert any(name.endswith("build_draft_task") for name, _ in queued)

    review = client.get(f"/api/v1/launch/{launch_id}/review", headers=auth)
    assert review.status_code == 200, review.text
    # The documented shape is the frontend's generated type: every key, nothing more.
    ReviewOut.model_validate(review.json())
    state = review.json()["state"]
    assert state["status"] == "building" and state["keep_polling"] is True
    polled = client.get(
        f"/api/v1/launch/{launch_id}/review/state?tries=2", headers=auth
    )
    assert polled.json()["state"]["tries"] == 3
    ReviewPollOut.model_validate(polled.json())

    launch.error_detail = {"title": "Rasm rad etildi", "message": "Boshqasini tanlang"}
    db.commit()
    detail = client.get(f"/api/v1/launch/{launch_id}/review/state", headers=auth)
    assert detail.json()["state"]["error_detail"]["title"] == "Rasm rad etildi"
    launch.error_detail = {}
    db.commit()

    launch.status = "ready"
    launch.targeting = {"geo_locations": {"countries": ["UZ"]}}
    db.commit()
    ready = client.get(f"/api/v1/launch/{launch_id}/review", headers=auth)
    assert ready.status_code == 200, ready.text
    ReviewOut.model_validate(ready.json())
    proposal = ready.json()["proposal"]
    assert proposal is not None and len(proposal["variants"]) == 1
    assert proposal["variants"][0]["asset"]["id"] == str(asset.id)

    refused = client.post(
        f"/api/v1/launch/{launch_id}/edit",
        json={"creatives": [{"position": 0, "primary_text": ""}]},
        headers=auth,
    )
    assert refused.status_code == 422, refused.text
    assert "creatives.1.primary_text" in refused.json()["problems"]
    renamed = client.post(
        f"/api/v1/launch/{launch_id}/name", json={"name": "Bahor osh"}, headers=auth
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["proposal"]["campaign_title"] == "Bahor osh"
    ReviewOut.model_validate(renamed.json())

    gone = client.post(f"/api/v1/launch/{launch_id}/discard", headers=auth)
    assert gone.status_code in (200, 400), gone.text


def test_someone_elses_launch_is_not_found(client: TestClient, db: Session) -> None:
    auth, _user = _ready(client, db)
    missing = client.get(
        "/api/v1/launch/00000000-0000-0000-0000-000000000000/review", headers=auth
    )
    assert missing.status_code == 404


def test_google_screen_is_hidden_until_switched_on(
    client: TestClient, db: Session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from app.common.config import settings

    auth, _user = _ready(client, db)
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    assert client.get("/api/v1/google", headers=auth).status_code == 404
    monkeypatch.setattr(settings, "google_oauth_client_id", "id")
    monkeypatch.setattr(settings, "google_ads_enabled", True)
    shown = client.get("/api/v1/google?period=30", headers=auth)
    assert shown.status_code == 200, shown.text
    assert shown.json()["period"] == "30" and shown.json()["screen"] is None
    refused = client.post(
        "/api/v1/google/budget",
        json={"external_id": "1", "budget": "abc"},
        headers=auth,
    )
    assert refused.status_code == 404
