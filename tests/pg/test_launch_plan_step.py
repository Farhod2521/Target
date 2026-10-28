"""The first screen over HTTP: the three-question picker, the goal reading, refusals."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.integrations.models import PageAccount
from tests.pg.conftest import sign_up
from tests.pg.test_launch_api import _ready


@pytest.fixture
def picker_v2(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "launch_goal_picker_v2", True)
    yield


def _opened(client: TestClient, db: Session) -> tuple[dict[str, str], str, User]:
    auth, user = _ready(client, db)
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    return auth, launch_id, user


def test_the_chat_row_opens_on_instagram_when_the_page_has_it(
    client: TestClient, db: Session, picker_v2: None
) -> None:
    auth, launch_id, user = _opened(client, db)
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == user.id))
    assert page is not None
    page.instagram_user_id = "ig_1"
    db.commit()

    plan = client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth)

    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["picker_v2"] is True
    assert body["initial"]["chat_channel"] == "instagram"
    assert body["initial"]["campaign_type"] == ""
    assert body["max_question_chars"] == 80


def test_an_instagram_address_for_a_site_offers_the_profile_goal(
    client: TestClient, db: Session, picker_v2: None
) -> None:
    auth, launch_id, _user = _opened(client, db)
    initial = client.get(
        f"/api/v1/launch/{launch_id}/plan?goal=traffic", headers=auth
    ).json()["initial"]

    refused = client.post(
        f"/api/v1/launch/{launch_id}/plan",
        json={
            "goal": "traffic",
            "daily_budget": initial["daily_budget"] or "10",
            "link_url": "instagram.com/bahor_cafe",
            "start_day": "tomorrow",
        },
        headers=auth,
    )

    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert "link_url" in body["problems"]
    assert body["hints"] == {"offer_outcome": "profile"}


def test_a_goal_typed_as_spaces_is_refused_before_the_model_is_asked(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, launch_id, _user = _opened(client, db)
    before = len(queued)

    refused = client.post(
        f"/api/v1/launch/{launch_id}/plan/goal",
        json={"goal_text": " " * 40},
        headers=auth,
    )

    assert refused.status_code == 422, refused.text
    assert "goal_text" in refused.json()["problems"]
    assert len(queued) == before


def test_the_older_step_does_not_refuse_chat_questions_it_never_saves(
    client: TestClient, db: Session
) -> None:
    auth, launch_id, _user = _opened(client, db)
    goals = [
        item["goal"]
        for item in client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth).json()[
            "goals"
        ]
    ]
    if "messages" not in goals:
        pytest.skip("no chat goal offered to this business")

    answer = client.post(
        f"/api/v1/launch/{launch_id}/plan",
        json={"goal": "messages", "chat_questions": ["savol"] * 9},
        headers=auth,
    )

    assert "chat_questions" not in answer.json().get("problems", {})


def test_a_refused_start_names_its_reason(client: TestClient, db: Session) -> None:
    auth = sign_up(client)

    refused = client.post("/api/v1/launch", headers=auth)

    assert refused.status_code >= 400, refused.text
    assert refused.json()["code"] not in {"", "domain_error"}
