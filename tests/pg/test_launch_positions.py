"""Which app, and where inside it, as the proposal editor saves them."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import DraftSection
from app.modules.ads.models import CampaignLaunch
from core.targeting.placements import OFFERED_POSITIONS, PLACEMENT_KEYS
from tests.pg.test_launch_api import _ready


def _proposal(client: TestClient, db: Session) -> tuple[dict[str, str], str]:
    auth, _user = _ready(client, db)
    opened = client.post(
        "/api/v1/launch/drafts",
        json={"flow": "campaigns", "resume": None},
        headers=auth,
    )
    assert opened.status_code == 200, opened.text
    draft_id = opened.json()["id"]
    path = f"/api/v1/launch/drafts/{draft_id}"
    floor = client.get(path, headers=auth).json()["minBudget"]
    went = client.patch(
        path,
        json={
            "goal": "click",
            "linkUrl": "bahor.example",
            "dailyBudget": floor | {"minor": 500},
            "step": "media",
        },
        headers=auth,
    )
    assert went.status_code == 200, went.text
    launch = _launch(db, draft_id)
    proposal = draft_field.empty_draft()
    draft_field.choose(
        proposal, DraftSection.AUDIENCE, {"age_min": 25, "age_max": 45, "genders": []}
    )
    launch.draft = proposal
    launch.status = "ready"
    launch.targeting = {"geo_locations": {"countries": ["UZ"]}}
    db.commit()
    return auth, path


def _launch(db: Session, draft_id: str) -> CampaignLaunch:
    db.expire_all()
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    return launch


def _placements(db: Session, path: str) -> dict[str, Any]:
    targeting = _launch(db, path.rsplit("/", 1)[1]).targeting
    return {key: value for key, value in targeting.items() if key in PLACEMENT_KEYS}


def _edit(client: TestClient, path: str, auth: dict[str, str]) -> dict[str, Any]:
    editor = client.get(f"{path}/edit", headers=auth)
    assert editor.status_code == 200, editor.text
    return editor.json()


def test_the_editor_offers_every_position_and_ticks_the_defaults(
    client: TestClient, db: Session
) -> None:
    auth, path = _proposal(client, db)
    aud = _edit(client, path, auth)["aud"]
    assert aud["apps"] == "auto"
    assert aud["positions"] == {
        "instagram": ["stream", "story", "reels"],
        "facebook": ["feed", "story", "facebook_reels"],
    }
    options = aud["positionOptions"]
    for app, values in OFFERED_POSITIONS.items():
        assert [row["value"] for row in options[app]] == list(values)
        assert all(row["label"] for row in options[app])
    story = next(row for row in options["facebook"] if row["value"] == "story")
    assert story["needs"] == ["facebook.feed", "instagram.story"]


def test_one_app_and_the_positions_ticked_reach_the_spec(
    client: TestClient, db: Session
) -> None:
    auth, path = _proposal(client, db)
    tabs = _edit(client, path, auth)
    tabs["aud"] |= {
        "apps": "instagram",
        "positions": {"instagram": ["reels", "story"], "facebook": ["feed"]},
    }
    saved = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert saved.status_code == 200, saved.text
    assert _placements(db, path) == {
        "publisher_platforms": ["instagram"],
        "instagram_positions": ["story", "reels"],
    }
    shown = _edit(client, path, auth)["aud"]
    assert shown["apps"] == "instagram"
    assert shown["positions"]["instagram"] == ["story", "reels"]
    placements = saved.json()["proposal"]["audience"]["placements"]
    assert placements == "Faqat Instagram: Instagram Stories, Instagram Reels"

    tabs = _edit(client, path, auth)
    tabs["aud"]["age"] = [30, 40]
    assert client.put(f"{path}/edit", json=tabs, headers=auth).status_code == 200
    assert _placements(db, path)["instagram_positions"] == ["story", "reels"]


def test_only_the_app_changed_runs_on_its_default_positions(
    client: TestClient, db: Session
) -> None:
    """A screen that does not send positions keeps working."""
    auth, path = _proposal(client, db)
    tabs = _edit(client, path, auth)
    del tabs["aud"]["positions"], tabs["aud"]["positionOptions"]
    tabs["aud"]["apps"] = "facebook"
    saved = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert saved.status_code == 200, saved.text
    assert _placements(db, path) == {
        "publisher_platforms": ["facebook"],
        "facebook_positions": ["feed", "story", "facebook_reels"],
    }


def test_both_apps_take_their_own_positions(client: TestClient, db: Session) -> None:
    auth, path = _proposal(client, db)
    tabs = _edit(client, path, auth)
    tabs["aud"] |= {
        "apps": "fbig",
        "positions": {"instagram": ["story"], "facebook": ["story"]},
    }
    saved = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert saved.status_code == 200, saved.text
    assert _placements(db, path) == {
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["story"],
        "instagram_positions": ["story"],
    }


def test_back_to_automatic_leaves_no_placement(client: TestClient, db: Session) -> None:
    auth, path = _proposal(client, db)
    tabs = _edit(client, path, auth)
    tabs["aud"] |= {
        "apps": "instagram",
        "positions": tabs["aud"]["positions"] | {"instagram": ["stream"]},
    }
    assert client.put(f"{path}/edit", json=tabs, headers=auth).status_code == 200
    tabs = _edit(client, path, auth)
    tabs["aud"]["apps"] = "auto"
    assert client.put(f"{path}/edit", json=tabs, headers=auth).status_code == 200
    assert _placements(db, path) == {}
    assert _edit(client, path, auth)["aud"]["positions"]["instagram"] == [
        "stream",
        "story",
        "reels",
    ]


@pytest.mark.parametrize(
    ("apps", "positions", "said"),
    [
        ("instagram", {"instagram": [], "facebook": []}, "Kamida bitta"),
        ("instagram", {"instagram": ["explore"], "facebook": []}, "Ro'yxatdan"),
        ("facebook", {"instagram": [], "facebook": ["story"]}, "yolg'iz"),
        ("facebook", {"instagram": [], "facebook": ["marketplace"]}, "yolg'iz"),
        ("instagram", {"instagram": ["ig_search"], "facebook": []}, "yolg'iz"),
        ("instagram", {"instagram": ["profile_reels"], "facebook": []}, "yolg'iz"),
    ],
)
def test_a_choice_meta_would_refuse_is_refused_here(
    client: TestClient,
    db: Session,
    apps: str,
    positions: dict[str, list[str]],
    said: str,
) -> None:
    auth, path = _proposal(client, db)
    tabs = _edit(client, path, auth)
    tabs["aud"] |= {"apps": apps, "positions": positions}
    refused = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert refused.status_code == 422, refused.text
    assert said in str(refused.json())
    assert _placements(db, path) == {}
