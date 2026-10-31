"""The wizard as the cabinet asks for it: one draft, its taps kept until they are sent."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers import drafts
from tests.pg.conftest import sign_up
from tests.pg.test_launch_api import _ready


@pytest.fixture(autouse=True)
def quick_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(drafts.READING, "poll_seconds", 0)


def _opened(client: TestClient, db: Session) -> tuple[dict[str, str], str]:
    auth, _user = _ready(client, db)
    opened = client.post(
        "/api/v1/launch/drafts",
        json={"flow": "campaigns", "resume": None},
        headers=auth,
    )
    assert opened.status_code == 200, opened.text
    return auth, opened.json()["id"]


def test_the_plans_taps_wait_for_davom_etish(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, draft_id = _opened(client, db)
    path = f"/api/v1/launch/drafts/{draft_id}"
    first = client.get(path, headers=auth).json()
    assert first["status"] == "draft" and first["step"] == "plan"
    assert first["flow"] == "campaigns" and first["networkId"] == "meta"
    floor = first["minBudget"]

    tapped = client.patch(
        path,
        json={"goal": "click", "linkUrl": "bahor.example", "start": "tomorrow"},
        headers=auth,
    )
    assert tapped.status_code == 200, tapped.text
    assert tapped.json()["goal"] == "click" and tapped.json()["start"] == "tomorrow"
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    db.refresh(launch)
    assert not launch.answers.get("goal")
    assert client.get(path, headers=auth).json()["linkUrl"] == "bahor.example"

    no_site = client.patch(path, json={"step": "media", "linkUrl": ""}, headers=auth)
    assert no_site.status_code == 422, no_site.text
    assert "linkUrl" in no_site.json()["problems"]
    db.refresh(launch)
    assert not launch.answers.get("goal")

    budget = floor | {"minor": 500}
    went = client.patch(
        path,
        json={"step": "media", "linkUrl": "bahor.example", "dailyBudget": budget},
        headers=auth,
    )
    assert went.status_code == 200, went.text
    db.refresh(launch)
    assert launch.answers["goal"] == "traffic"
    assert launch.answers["link_url"].endswith("bahor.example")
    assert went.json()["step"] == "media" and went.json()["dailyBudget"] == budget


def test_a_ready_phrase_settles_the_goal(client: TestClient, db: Session) -> None:
    auth, draft_id = _opened(client, db)
    read = client.post(
        f"/api/v1/launch/drafts/{draft_id}/goal-reading",
        json={"phrase": "lead"},
        headers=auth,
    )
    assert read.status_code == 200, read.text
    assert read.json()["goal"] == "lead" and read.json()["method"] == "instant_form"
    assert read.json()["reading"]["by"] == "phrase"

    short = client.post(
        f"/api/v1/launch/drafts/{draft_id}/goal-reading",
        json={"text": "ha"},
        headers=auth,
    )
    assert short.status_code == 422 and "text" in short.json()["problems"]


def test_the_offer_typed_is_kept_with_the_launch(
    client: TestClient, db: Session
) -> None:
    auth, draft_id = _opened(client, db)
    path = f"/api/v1/launch/drafts/{draft_id}"
    typed = client.patch(path, json={"offer": "Yangi osh, chegirma"}, headers=auth)
    assert typed.status_code == 200, typed.text
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    db.refresh(launch)
    assert launch.answers["shared_text"] == "Yangi osh, chegirma"

    each = client.patch(
        path,
        json={"textMode": "each", "media": ["a_1"], "offers": {"a_1": "Osh"}},
        headers=auth,
    )
    body = each.json()
    assert body["textMode"] == "each" and body["offers"] == {"a_1": "Osh"}
    assert body["media"] == ["a_1"] and body["offer"] == "Yangi osh, chegirma"


def test_someone_elses_draft_is_not_found(client: TestClient, db: Session) -> None:
    _auth, draft_id = _opened(client, db)
    stranger = sign_up(client, email="boshqa@example.com")
    assert (
        client.get(f"/api/v1/launch/drafts/{draft_id}", headers=stranger).status_code
        == 404
    )
