"""The wizard as the cabinet asks for it: one draft, its taps kept until they are sent."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import DraftSection, MediaKind
from app.modules.ads.models import Campaign, CampaignLaunch, GoogleLaunch, MediaAsset
from app.modules.ads.routers import drafts
from app.modules.ads.selectors.variants import launch_variants
from app.modules.integrations.models import AdAccount
from tests.pg.conftest import sign_up
from tests.pg.test_launch_api import _ready
from tests.pg.test_launch_media_uploads import _picture, media_root  # noqa: F401


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


def test_the_pictures_then_the_proposal_and_its_editor(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, draft_id = _opened(client, db)
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
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    asset = MediaAsset(
        owner_id=launch.owner_id,
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

    ticked = client.patch(
        path, json={"media": [str(asset.id)], "offer": "Yangi osh"}, headers=auth
    )
    assert ticked.status_code == 200, ticked.text
    built = client.post(f"{path}/build", headers=auth)
    assert built.status_code == 200, built.text
    assert built.json()["status"] == "building"
    assert any(name.endswith("build_draft_task") for name, _ in queued)
    # Sent once: the tile the launch holds now is not sent again.
    again = client.post(f"{path}/build", headers=auth)
    assert again.status_code == 200, again.text
    assert len(launch_variants(db, launch=launch)) == 1

    unknown = client.post(f"{path}/regenerate/nothing", headers=auth)
    assert unknown.status_code == 400

    db.refresh(launch)
    proposal = draft_field.empty_draft()
    draft_field.choose(
        proposal, DraftSection.AUDIENCE, {"age_min": 25, "age_max": 45, "genders": []}
    )
    launch.draft = proposal
    launch.status = "ready"
    launch.targeting = {"geo_locations": {"countries": ["UZ"]}}
    db.commit()
    ready = client.get(path, headers=auth).json()
    assert ready["status"] == "ready" and len(ready["proposal"]["ads"]) == 1

    named = client.post(f"{path}/name", json={"name": "Bahor osh"}, headers=auth)
    assert named.status_code == 200, named.text
    assert named.json()["proposal"]["name"] == "Bahor osh"

    editor = client.get(f"{path}/edit", headers=auth)
    assert editor.status_code == 200, editor.text
    tabs = editor.json()
    same = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert same.status_code == 200, same.text
    tabs["ads"][0]["text"] = "Osh tayyor, buyurtma bering"
    saved = client.put(f"{path}/edit", json=tabs, headers=auth)
    assert saved.status_code == 200, saved.text
    assert saved.json()["proposal"]["ads"][0]["text"] == "Osh tayyor, buyurtma bering"

    gone = client.post(f"{path}/discard", headers=auth)
    assert gone.status_code == 204, gone.text


def test_the_chat_questions_are_read_where_they_come(
    client: TestClient, db: Session
) -> None:
    auth, draft_id = _opened(client, db)
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    launch.answers = {
        **launch.answers,
        "chat_questions_reading": {"state": "done", "questions": ["Narxi qancha?"]},
    }
    db.commit()
    read = client.get(f"/api/v1/launch/drafts/{draft_id}/chat-questions", headers=auth)
    assert read.status_code == 200, read.text
    assert read.json() == {"state": "done", "questions": ["Narxi qancha?"]}


@pytest.mark.usefixtures("media_root")
def test_the_pictures_step_reads_both_grids_and_takes_uploads(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, draft_id = _opened(client, db)
    path = f"/api/v1/launch/drafts/{draft_id}"
    floor = client.get(path, headers=auth).json()["minBudget"]
    client.patch(
        path,
        json={
            "goal": "click",
            "linkUrl": "bahor.example",
            "dailyBudget": floor | {"minor": 500},
            "step": "media",
        },
        headers=auth,
    )
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    picture = MediaAsset(
        owner_id=launch.owner_id,
        ad_account_id=launch.ad_account_id,
        provider=launch.provider,
        kind=MediaKind.IMAGE,
        external_id="hash_1",
        name="osh.jpg",
        width=1080,
        height=1080,
    )
    db.add(picture)
    db.commit()

    shown = client.get(f"{path}/media", headers=auth)
    assert shown.status_code == 200, shown.text
    grid = shown.json()
    assert [tile["id"] for tile in grid["library"]] == [str(picture.id)]
    assert grid["held"] == {} and grid["maxImageMb"] > 0

    data = _picture()
    whole = client.post(
        f"{path}/media/upload",
        files={"file": ("tort.jpg", data, "image/jpeg")},
        headers=auth,
    )
    assert whole.status_code == 200, whole.text
    assert whole.json()["id"].startswith("upload-")
    assert any(name.endswith("upload_to_library_task") for name, _ in queued)

    upload_id = str(uuid.uuid4())
    piece = client.post(
        f"{path}/media/upload/chunk",
        content=data,
        headers=auth
        | {
            "X-Upload-Id": upload_id,
            "X-Upload-Size": str(len(data)),
            "X-Upload-Offset": "0",
        },
    )
    assert piece.status_code == 200 and piece.json()["offset"] == len(data)
    done = client.post(
        f"{path}/media/upload/finish",
        json={"uploadId": upload_id, "total": len(data), "name": "non.jpg"},
        headers=auth,
    )
    assert done.status_code == 200, done.text
    held = client.get(f"{path}/media", headers=auth).json()
    assert len(held["uploads"]) == 2 and len(held["held"]) == 2

    released = client.delete(f"{path}/media/held/0", headers=auth)
    assert released.status_code == 200, released.text
    assert len(released.json()["held"]) == 1


def _google(
    db: Session, monkeypatch: pytest.MonkeyPatch, user: User
) -> tuple[AdAccount, GoogleLaunch]:
    monkeypatch.setattr(settings, "google_oauth_client_id", "id")
    monkeypatch.setattr(settings, "google_ads_enabled", True)
    account = db.scalar(select(AdAccount).where(AdAccount.owner_id == user.id))
    assert account is not None
    account.provider = "google"
    account.currency = "USD"
    launch = GoogleLaunch(
        owner_id=user.id,
        ad_account_id=account.id,
        currency="USD",
        final_url="https://bahor.example",
        phone="",
        places=[],
        keywords=[],
        negative_keywords=[],
        headlines=[],
        descriptions=[],
        volumes={},
        created_refs={},
    )
    db.add(launch)
    db.commit()
    return account, launch


def test_the_google_wizard_through_the_same_draft(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    _account, launch = _google(db, monkeypatch, user)
    path = f"/api/v1/launch/drafts/{launch.id}"
    first = client.get(path, headers=auth)
    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["flow"], body["networkId"]) == ("google", "google")
    assert (body["status"], body["step"]) == ("draft", "plan")
    assert client.get(f"{path}/areas", headers=auth).status_code == 200

    money = {"minor": 500, "currency": "USD", "exponent": 2}
    tapped = client.patch(
        path, json={"goal": "call", "dailyBudget": money}, headers=auth
    )
    assert tapped.json()["goal"] == "call" and tapped.json()["dailyBudget"] == money
    no_phone = client.patch(path, json={"step": "words"}, headers=auth)
    assert no_phone.status_code == 422, no_phone.text
    assert "phone" in no_phone.json()["problems"]
    assert no_phone.json()["code"] == "google_phone_required"

    went = client.patch(path, json={"goal": "click", "step": "words"}, headers=auth)
    assert went.status_code == 200, went.text
    assert (went.json()["status"], went.json()["step"]) == ("building", "words")
    db.refresh(launch)
    assert launch.goal == "visits" and launch.daily_budget_minor == 500
    prepared = [
        name for name, _ in queued if name.endswith("prepare_google_launch_task")
    ]
    assert len(prepared) == 1

    launch.status = "ready"
    launch.ai_written_at = utcnow()
    launch.keywords = [{"text": "osh"}]
    launch.volumes = {"osh": 90}
    launch.headlines = ["Bahor osh", "Yangi osh", "Issiq osh"]
    launch.descriptions = ["Mazali osh yetkazib beramiz", "Bugun buyurtma bering"]
    db.commit()
    words = client.get(path, headers=auth).json()
    assert (words["status"], words["step"]) == ("draft", "words")
    assert words["google"]["keywords"] == [{"text": "osh", "volume": 90}]

    back = client.patch(path, json={"step": "words"}, headers=auth)
    assert back.status_code == 200, back.text
    db.refresh(launch)
    assert launch.status == "ready", "going back must not write the words over"

    saved = client.put(
        f"{path}/google",
        json=words["google"] | {"url": "https://yangi.example", "minus": ["bepul"]},
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["status"], saved.json()["step"]) == ("ready", "review")
    assert saved.json()["linkUrl"] == "https://yangi.example"
    assert saved.json()["proposal"]["goal"]["site"] == "yangi.example"

    made = client.post(f"{path}/create", headers=auth)
    assert made.status_code == 200, made.text
    assert made.json()["status"] == "creating"
    assert made.json()["creation"]["stage"] == 1


def test_the_google_screen_answers_the_cabinets_shape(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _ready(client, db)
    account, _launch = _google(db, monkeypatch, user)
    db.add(
        Campaign(
            owner_id=user.id,
            provider="google",
            external_id="111",
            ad_account_id=account.id,
            name="Qidiruv",
            delivery="paused",
            status="PAUSED",
            currency="USD",
            daily_budget_minor=700,
            synced_at=utcnow(),
        )
    )
    db.commit()
    shown = client.get("/api/v1/google/screen?period=30", headers=auth)
    assert shown.status_code == 200, shown.text
    screen = shown.json()["screen"]
    assert screen["period"] == "30" and screen["anyPending"] is False
    row = screen["campaigns"][0]
    assert (row["id"], row["delivery"]) == ("111", "paused")
    assert row["dailyBudget"]["minor"] == 700
    assert row["figures"]["costPerResult"] is None
    pressed = client.post(
        "/api/v1/google/switch",
        json={"level": "campaign", "id": "111", "wanted": "resume"},
        headers=auth,
    )
    assert pressed.status_code == 200, pressed.text
    assert pressed.json()["message"]
