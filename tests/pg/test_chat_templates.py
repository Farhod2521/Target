"""«Xabar yozishsin» templates: a greeting and its questions kept under a name."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.deletion import delete_rows
from app.modules.ads.models import CampaignLaunch, ChatTemplate
from app.modules.ads.services import chat_templates
from app.modules.integrations.models import PageAccount
from tests.pg.conftest import sign_up
from tests.pg.test_launch_drafts import _opened

BODY = {
    "name": "Yozgi aksiya",
    "welcomeText": "  Salom! Yozing.  ",
    "chatQuestions": [
        "Narxi qancha?",
        " narxi  qancha? ",
        "",
        "Yetkazib berish bormi?",
    ],
    "chatAnswers": [" 100 ming so'm ", "boshqa", "yo'q", ""],
}


def _path(draft_id: str) -> str:
    return f"/api/v1/launch/drafts/{draft_id}/chat-templates"


def test_a_template_is_saved_listed_written_over_and_deleted(
    client: TestClient, db: Session
) -> None:
    auth, draft_id = _opened(client, db)
    path = _path(draft_id)
    empty = client.get(path, headers=auth)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"items": [], "maxItems": 20, "maxNameChars": 40}

    saved = client.post(path, json=BODY, headers=auth)
    assert saved.status_code == 200, saved.text
    (item,) = saved.json()["items"]
    assert item["name"] == "Yozgi aksiya"
    assert item["welcomeText"] == "Salom! Yozing."
    assert item["chatQuestions"] == ["Narxi qancha?", "Yetkazib berish bormi?"]
    # Each answer stays beside its own question when rows are dropped.
    assert item["chatAnswers"] == ["100 ming so'm", ""]

    # The same name in another letter case writes over, it does not add.
    over = client.post(
        path,
        json={"name": " yozgi  AKSIYA ", "welcomeText": "Assalomu alaykum!"},
        headers=auth,
    )
    assert over.status_code == 200, over.text
    (item2,) = over.json()["items"]
    assert item2["id"] == item["id"]
    assert item2["name"] == "yozgi AKSIYA"
    assert item2["welcomeText"] == "Assalomu alaykum!"
    assert item2["chatQuestions"] == [] and item2["chatAnswers"] == []

    second = client.post(path, json=BODY | {"name": "Ikkinchi"}, headers=auth)
    assert [row["name"] for row in second.json()["items"]] == [
        "Ikkinchi",
        "yozgi AKSIYA",
    ]

    gone = client.delete(f"{path}/{item['id']}", headers=auth)
    assert gone.status_code == 200, gone.text
    assert [row["name"] for row in gone.json()["items"]] == ["Ikkinchi"]
    again = client.delete(f"{path}/{item['id']}", headers=auth)
    assert again.status_code == 404, again.text


def test_a_template_is_refused_field_by_field(client: TestClient, db: Session) -> None:
    auth, draft_id = _opened(client, db)
    path = _path(draft_id)

    blank = client.post(path, json={"name": "  ", "welcomeText": ""}, headers=auth)
    assert blank.status_code == 422, blank.text
    assert set(blank.json()["problems"]) == {"name", "welcomeText"}

    long = client.post(
        path,
        json={
            "name": "n" * 41,
            "welcomeText": "s" * 301,
            "chatQuestions": ["q" * 81],
            "chatAnswers": ["a" * 301],
        },
        headers=auth,
    )
    assert long.status_code == 422, long.text
    assert set(long.json()["problems"]) == {
        "name",
        "welcomeText",
        "chatQuestions",
        "chatAnswers",
    }

    many = client.post(
        path,
        json={
            "name": "Ko'p",
            "welcomeText": "Salom",
            "chatQuestions": [f"Savol {n}?" for n in range(5)],
        },
        headers=auth,
    )
    assert many.status_code == 422, many.text
    assert set(many.json()["problems"]) == {"chatQuestions"}
    assert db.scalar(select(ChatTemplate)) is None


def test_no_more_than_the_limit_is_kept_but_a_kept_name_still_saves(
    client: TestClient, db: Session
) -> None:
    auth, draft_id = _opened(client, db)
    path = _path(draft_id)
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None
    for n in range(chat_templates.MAX_TEMPLATES):
        db.add(
            ChatTemplate(
                owner_id=launch.owner_id,
                page_id=launch.page_id,
                name=f"Shablon {n}",
                welcome_text="Salom",
            )
        )
    db.commit()

    full = client.post(path, json=BODY, headers=auth)
    assert full.status_code == 422, full.text
    assert set(full.json()["problems"]) == {"name"}

    over = client.post(path, json=BODY | {"name": "shablon 3"}, headers=auth)
    assert over.status_code == 200, over.text
    assert len(over.json()["items"]) == chat_templates.MAX_TEMPLATES


def test_templates_stay_with_their_owner_and_page(
    client: TestClient, db: Session
) -> None:
    auth, draft_id = _opened(client, db)
    path = _path(draft_id)
    saved = client.post(path, json=BODY, headers=auth).json()["items"][0]
    launch = db.get(CampaignLaunch, uuid.UUID(draft_id))
    assert launch is not None and launch.page_id is not None

    # Another page of the same owner has its own list.
    page = db.get(PageAccount, launch.page_id)
    assert page is not None
    other = PageAccount(
        owner_id=page.owner_id,
        connection_id=page.connection_id,
        provider=page.provider,
        external_id="page_2",
        name="Boshqa",
        token_encrypted=b"x",
    )
    db.add(other)
    db.flush()
    db.add(
        ChatTemplate(
            owner_id=launch.owner_id,
            page_id=other.id,
            name="Boshqa sahifa",
            welcome_text="Salom",
        )
    )
    db.commit()
    assert [row["name"] for row in client.get(path, headers=auth).json()["items"]] == [
        "Yozgi aksiya"
    ]

    # A stranger reads, saves and deletes nothing here.
    stranger = sign_up(client, email="boshqa@example.com", phone="+998901112244")
    assert client.get(path, headers=stranger).status_code == 404
    assert client.post(path, json=BODY, headers=stranger).status_code == 404
    assert client.delete(f"{path}/{saved['id']}", headers=stranger).status_code == 404
    assert client.get(path).status_code == 401

    # A page that goes takes its templates with it.
    delete_rows(db, PageAccount.__table__, PageAccount.id == other.id)
    db.commit()
    assert db.scalar(select(ChatTemplate.name)) == "Yozgi aksiya"
