"""The office reads the answers owners get from a refusal, and corrects them."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.chat.models import RefusalAnswer
from app.modules.chat.selectors.refusal import ready_answer
from app.modules.chat.services.refusal import keep_answer
from core.chat.refusal import ChangeFacts
from tests.pg.test_office_actions import _staff

URL = "/api/v1/office/refusals"


def _answer(db: Session, key: str = "meta:100/1", **fields: object) -> RefusalAnswer:
    row = RefusalAnswer(key=key, answer_uz="AI matni", prompt_version="v2", **fields)
    db.add(row)
    db.commit()
    return row


def test_a_customer_cannot_open_the_list(client: TestClient, db: Session) -> None:
    _user, headers = _staff(db, email="nobody@example.com")

    assert client.get(URL, headers=headers).status_code == 404


def test_the_list_shows_what_needs_a_person_first(
    client: TestClient, db: Session
) -> None:
    _user, headers = _staff(db, Role.SUPPORT, email="s@example.com")
    _answer(db, key="meta:1/1", hits=1, answer_ru="ru", answer_en="en")
    _answer(db, key="change:meta:2/2", hits=9, held=True)
    _answer(db, key="meta:3/3", hits=3)
    retired = RefusalAnswer(key="meta:4/4", answer_uz="eski", prompt_version="v1")
    db.add(retired)
    db.commit()

    everything = client.get(URL, headers=headers).json()
    held = client.get(URL, params={"tab": "held"}, headers=headers).json()
    missing = client.get(URL, params={"tab": "untranslated"}, headers=headers).json()
    old = client.get(URL, params={"tab": "retired"}, headers=headers).json()
    found = client.get(URL, params={"q": "3/3"}, headers=headers).json()

    assert [row["key"] for row in everything["rows"]][0] == "change:meta:2/2"
    assert everything["rows"][0]["operation"] == "change"
    assert everything["held"] == 1 and everything["total"] == 4
    assert [row["key"] for row in held["rows"]] == ["change:meta:2/2"]
    assert {row["key"] for row in missing["rows"]} == {"change:meta:2/2", "meta:3/3"}
    assert [row["key"] for row in old["rows"]] == ["meta:4/4"]
    assert old["rows"][0]["retired"] is True
    assert [row["key"] for row in found["rows"]] == ["meta:3/3"]


def test_a_saved_answer_is_shown_at_once_and_journalled(
    client: TestClient, db: Session
) -> None:
    actor, headers = _staff(db, Role.SUPPORT, email="s2@example.com")
    row = _answer(db, held=True)
    assert ready_answer(db, key=row.key, language="uz") is None

    saved = client.patch(
        f"{URL}/{row.id}", json={"answer_uz": " Ofis matni "}, headers=headers
    )

    assert saved.status_code == 200
    assert saved.json()["written_by"] == "office" and saved.json()["held"] is False
    assert saved.json()["edited_at"]
    db.expire_all()
    assert ready_answer(db, key=row.key, language="uz").text == "Ofis matni"
    trace = db.scalar(
        select(StaffAction).where(StaffAction.kind == ActionKind.REFUSAL_EDITED)
    )
    assert trace is not None and trace.actor_id == actor.id
    assert trace.detail == {"key": row.key, "changed": ["answer_uz"]}


def test_an_old_answer_is_revived_by_saving_it(client: TestClient, db: Session) -> None:
    _actor, headers = _staff(db, Role.OWNER, email="o@example.com")
    row = RefusalAnswer(key="meta:5/5", answer_uz="eski", prompt_version="v1")
    db.add(row)
    db.commit()
    assert ready_answer(db, key=row.key, language="uz") is None

    client.patch(f"{URL}/{row.id}", json={"answer_ru": "старый"}, headers=headers)

    db.expire_all()
    assert ready_answer(db, key=row.key, language="uz").text == "eski"


def test_claude_never_writes_over_the_office(client: TestClient, db: Session) -> None:
    _actor, headers = _staff(db, Role.OWNER, email="o2@example.com")
    row = _answer(db)
    client.patch(f"{URL}/{row.id}", json={"answer_uz": "Ofis"}, headers=headers)

    keep_answer(
        db,
        key=row.key,
        texts={"uz": "AI yangi"},
        facts=ChangeFacts(change="x", level="y"),
        version="v3",
    )

    db.expire_all()
    assert db.get(RefusalAnswer, row.id).answer_uz == "Ofis"


def test_an_answer_cannot_be_emptied(client: TestClient, db: Session) -> None:
    _actor, headers = _staff(db, Role.OWNER, email="o3@example.com")
    row = _answer(db)

    refused = client.patch(f"{URL}/{row.id}", json={"answer_uz": "  "}, headers=headers)

    assert refused.status_code == 400
