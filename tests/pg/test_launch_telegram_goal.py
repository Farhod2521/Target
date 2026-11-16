"""«Telegramga o'tsin»: the first step's own goal, kept as a visit whose link opens Telegram."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers import drafts
from app.modules.ads.selectors.campaign_type import (
    campaign_type_choices,
    effective_campaign_type,
)
from app.modules.ads.selectors.copy_notes import button_action
from app.modules.ads.selectors.goals import goal_optimization
from app.modules.ads.selectors.telegram import NOT_TELEGRAM, telegram_link
from app.modules.ads.services.proposal import prompt_variables
from app.modules.businesses.selectors import business_for_page
from core.agent.copy_check import AdWords, check_against_offer
from tests.pg.test_launch_api import _ready


@pytest.fixture(autouse=True)
def quick_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(drafts.READING, "poll_seconds", 0)


@pytest.mark.parametrize(
    ("typed", "link"),
    [
        ("@bahor_cafe", "https://t.me/bahor_cafe"),
        ("bahor_cafe", "https://t.me/bahor_cafe"),
        (" t.me/bahor_cafe ", "https://t.me/bahor_cafe"),
        ("https://t.me/bahor_cafe/", "https://t.me/bahor_cafe"),
        ("http://telegram.me/bahor_cafe", "https://t.me/bahor_cafe"),
        ("https://t.me/s/bahor_cafe", "https://t.me/bahor_cafe"),
        ("t.me/+AbCdEfGh12345678", "https://t.me/+AbCdEfGh12345678"),
        ("t.me/joinchat/AbCdEfGh1234", "https://t.me/joinchat/AbCdEfGh1234"),
        ("t.me/bahor_bot?start=meta", "https://t.me/bahor_bot?start=meta"),
        ("t.me/bahor_cafe/125", "https://t.me/bahor_cafe/125"),
        ("tg://resolve?domain=bahor_cafe", "https://t.me/bahor_cafe"),
        ("", ""),
        ("bahor.example", ""),
        ("https://bahor.example/t.me/bahor", ""),
        ("https://t.me.evil.example/bahor", ""),
        ("instagram.com/bahor_cafe", ""),
        ("@ab", ""),
        ("t.me/", ""),
        ("+998901234567", ""),
    ],
)
def test_a_telegram_address_is_read_however_it_is_typed(typed: str, link: str) -> None:
    assert telegram_link(typed) == link


def _opened(client: TestClient, db: Session) -> tuple[dict[str, str], str]:
    auth, _user = _ready(client, db)
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    return auth, launch_id


def _saved(client: TestClient, auth: dict[str, str], launch_id: str, **body: str):
    initial = client.get(
        f"/api/v1/launch/{launch_id}/plan?goal={body['goal']}", headers=auth
    ).json()["initial"]
    return client.post(
        f"/api/v1/launch/{launch_id}/plan",
        json={"daily_budget": initial["daily_budget"] or "10", **body},
        headers=auth,
    )


def test_the_first_step_offers_telegram_beside_the_site(
    client: TestClient, db: Session
) -> None:
    auth, launch_id = _opened(client, db)

    plan = client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth).json()

    goals = [row["goal"] for row in plan["goals"]]
    assert goals[goals.index("traffic") + 1] == "telegram"
    labels = {row["goal"]: row["label"] for row in plan["goals"]}
    assert labels["telegram"] == "Telegramga o'tsin"
    phrases = {row["goal"]: row["phrase"] for row in plan["picker"]["goal_phrases"]}
    assert phrases["telegram"] == "Telegram kanalimga o'tsin"


def test_the_business_site_is_not_offered_as_the_telegram_address(
    client: TestClient, db: Session
) -> None:
    auth, launch_id = _opened(client, db)

    site = client.get(
        f"/api/v1/launch/{launch_id}/plan?goal=traffic", headers=auth
    ).json()
    telegram = client.get(
        f"/api/v1/launch/{launch_id}/plan?goal=telegram", headers=auth
    ).json()

    assert site["initial"]["link_url"].startswith("https://bahor.example")
    assert telegram["initial"]["goal"] == "telegram"
    assert telegram["initial"]["link_url"] == ""
    assert telegram["frame"]["needs_link"] is True


def test_a_name_becomes_the_link_and_the_visit_is_bought_by_the_tap(
    client: TestClient, db: Session
) -> None:
    auth, launch_id = _opened(client, db)

    saved = _saved(client, auth, launch_id, goal="telegram", link_url="@bahor_cafe")

    assert saved.status_code == 200, saved.text
    launch = db.get(CampaignLaunch, uuid.UUID(launch_id))
    assert launch is not None
    db.refresh(launch)
    assert launch.answers["goal"] == "traffic"
    assert launch.answers["link_kind"] == "telegram"
    assert launch.answers["link_url"] == "https://t.me/bahor_cafe"
    # Nothing is counted inside Telegram: the tap on the link is what Meta is asked for.
    assert effective_campaign_type(launch=launch) == "site_link_clicks"
    assert goal_optimization(db, launch=launch) == "LINK_CLICKS"
    choices = campaign_type_choices(launch=launch)
    assert choices is not None
    assert [option.key for option in choices.options] == ["site_link_clicks"]
    # The step opens on what was chosen, with its address.
    plan = client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth).json()
    assert plan["initial"]["goal"] == "telegram"
    assert plan["initial"]["link_url"] == "https://t.me/bahor_cafe"


def test_a_site_is_refused_as_a_telegram_address(
    client: TestClient, db: Session
) -> None:
    auth, launch_id = _opened(client, db)

    refused = _saved(
        client, auth, launch_id, goal="telegram", link_url="https://bahor.example"
    )

    assert refused.status_code == 422, refused.text
    assert refused.json()["problems"]["link_url"] == NOT_TELEGRAM


def test_going_back_to_the_site_leaves_telegram_behind(
    client: TestClient, db: Session
) -> None:
    auth, launch_id = _opened(client, db)
    assert _saved(client, auth, launch_id, goal="telegram", link_url="@bahor_cafe")

    saved = _saved(client, auth, launch_id, goal="traffic", link_url="bahor.example")

    assert saved.status_code == 200, saved.text
    launch = db.get(CampaignLaunch, uuid.UUID(launch_id))
    assert launch is not None
    db.refresh(launch)
    assert launch.answers["goal"] == "traffic"
    assert not launch.answers.get("link_kind")
    assert effective_campaign_type(launch=launch) == "site_page_views"
    plan = client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth).json()
    assert plan["initial"]["goal"] == "traffic"


def test_the_words_are_written_for_telegram(client: TestClient, db: Session) -> None:
    auth, launch_id = _opened(client, db)
    assert _saved(client, auth, launch_id, goal="telegram", link_url="@bahor_cafe")
    launch = db.get(CampaignLaunch, uuid.UUID(launch_id))
    assert launch is not None
    db.refresh(launch)
    business = business_for_page(db, owner=launch.owner, page=launch.page)
    assert business is not None

    told = prompt_variables(db, launch=launch, business=business)

    assert button_action(db, launch=launch) == "telegram"
    assert told["button_action"] == "telegram"
    assert told["goal_label"] == "Telegramga o'tsin"


def test_copy_that_asks_to_write_fits_telegram_and_a_form_does_not() -> None:
    def codes(text: str) -> list[str]:
        words = AdWords(primary_text=text, headline="Bahor", description="")
        found = check_against_offer(words=words, facts=text, sends_to="telegram")
        return [row.code for row in found]

    assert codes("Yangi taomlar har kuni. Telegramda xabar yozing va band qiling") == []
    assert codes("Yangi taomlar har kuni. Bizga ariza qoldiring hoziroq") == [
        "action_mismatch"
    ]


def test_the_cabinet_draft_carries_telegram_as_a_goal_of_its_own(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, _user = _ready(client, db)
    draft_id = client.post(
        "/api/v1/launch/drafts",
        json={"flow": "campaigns", "resume": None},
        headers=auth,
    ).json()["id"]
    path = f"/api/v1/launch/drafts/{draft_id}"

    first = client.get(path, headers=auth).json()
    assert "telegram" in first["offeredGoals"]
    assert {"goal": "telegram", "phrase": "Telegram kanalimga o'tsin"} in first[
        "goalPhrases"
    ]

    tapped = client.patch(path, json={"goal": "telegram"}, headers=auth)
    assert tapped.status_code == 200, tapped.text
    assert tapped.json()["goal"] == "telegram"
    assert tapped.json()["linkUrl"] == ""

    refused = client.patch(
        path, json={"step": "media", "linkUrl": "bahor.example"}, headers=auth
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["problems"]["linkUrl"] == NOT_TELEGRAM

    sent = client.patch(
        path,
        json={
            "step": "media",
            "linkUrl": "@bahor_cafe",
            "dailyBudget": first["minBudget"] | {"minor": 500},
        },
        headers=auth,
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["goal"] == "telegram"
    assert body["linkUrl"] == "https://t.me/bahor_cafe"
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    db.refresh(launch)
    assert launch.answers["goal"] == "traffic"
    assert launch.answers["link_kind"] == "telegram"


def test_the_ready_phrase_settles_on_telegram(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, _user = _ready(client, db)
    draft_id = client.post(
        "/api/v1/launch/drafts",
        json={"flow": "campaigns", "resume": None},
        headers=auth,
    ).json()["id"]

    read = client.post(
        f"/api/v1/launch/drafts/{draft_id}/goal-reading",
        json={"phrase": "telegram"},
        headers=auth,
    )

    assert read.status_code == 200, read.text
    body = read.json()
    assert body["reading"]["state"] == "found"
    assert body["reading"]["goal"] == "telegram"
    assert body["goal"] == "telegram"
