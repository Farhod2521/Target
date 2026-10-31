"""The goal said in words, read by the worker, as the cabinet presses it."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.common.config import settings
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers import drafts
from app.modules.ads.services import readings
from core.agent.schemas import GoalChoice, GoalIntent
from tests.pg.test_launch_api import _ready

WORDS = "Odamlar saytimga kirib ko'rsin"


def _worker(
    monkeypatch: pytest.MonkeyPatch,
    pg_factory: sessionmaker[Session],
    queued: list[tuple[str, tuple[object, ...]]],
    answer: Any,
) -> None:
    """The model's answer, and the worker running while the press waits."""

    def asked(*, version: str, schema: Any, variables: dict[str, object]) -> Any:
        return SimpleNamespace(value=answer)

    def sleep(_seconds: float) -> None:
        for name, args in queued:
            if name.endswith("detect_goal_task"):
                with pg_factory() as session:
                    readings.detect_goal(
                        session, launch_id=str(args[0]), token=str(args[1])
                    )
        queued.clear()

    monkeypatch.setattr(readings, "ask_goal_intent", asked)
    monkeypatch.setattr(readings, "_record", lambda *_args: None)
    monkeypatch.setattr(drafts, "time", SimpleNamespace(sleep=sleep))


def _opened(client: TestClient, db: Session) -> tuple[dict[str, str], str]:
    auth, _user = _ready(client, db)
    opened = client.post(
        "/api/v1/launch/drafts",
        json={"flow": "campaigns", "resume": None},
        headers=auth,
    )
    assert opened.status_code == 200, opened.text
    return auth, opened.json()["id"]


@pytest.mark.parametrize(
    ("picker_v2", "answer"),
    [
        (
            False,
            GoalIntent(goals=["traffic"], quote="saytimga kirib", wants_sale=False),
        ),
        (
            True,
            GoalChoice.model_construct(
                choice="site_page_views",
                alternatives=[],
                quote="saytimga kirib",
                wants_sale=False,
            ),
        ),
    ],
    ids=["list", "rows"],
)
@pytest.mark.parametrize("toggled", [False, True], ids=["opened", "toggled"])
def test_the_words_read_reach_the_proposal(
    client: TestClient,
    db: Session,
    pg_factory: sessionmaker[Session],
    queued: list[tuple[str, tuple[object, ...]]],
    monkeypatch: pytest.MonkeyPatch,
    picker_v2: bool,
    answer: Any,
    toggled: bool,
) -> None:
    monkeypatch.setattr(settings, "launch_goal_picker_v2", picker_v2)
    _worker(monkeypatch, pg_factory, queued, answer)
    auth, draft_id = _opened(client, db)
    path = f"/api/v1/launch/drafts/{draft_id}"
    if toggled:
        client.patch(path, json={"goalMode": "list"}, headers=auth)
        client.patch(path, json={"goalMode": "words"}, headers=auth)

    read = client.post(f"{path}/goal-reading", json={"text": WORDS}, headers=auth)
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["reading"]["state"] == "found", body["reading"]
    assert body["reading"]["goal"] == "click" and body["goal"] == "click"
    assert body["goalWords"] == WORDS and body["goalMode"] == "words"

    went = client.patch(
        path,
        json={
            "linkUrl": "bahor.example",
            "dailyBudget": body["minBudget"] | {"minor": 500},
            "step": "media",
        },
        headers=auth,
    )
    assert went.status_code == 200, went.text
    assert went.json()["goal"] == "click" and went.json()["goalWords"] == WORDS
    assert went.json()["reading"] and went.json()["reading"]["goal"] == "click"
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    db.refresh(launch)
    assert launch.answers["goal_text"] == WORDS
