"""Before a request to Support is shown, the client is asked what was wrong
with the assistant's answers (owner's decision, 2026-11-19). Their reply
lands on the office's «Meta & AI» → AI chat list, and the send button
follows it - with no model call and nothing counted."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assistant.models import AssistantFeedback
from app.modules.backoffice.constants import Role
from core.assistant.tools import TicketDraft
from tests.pg.test_assistant import (
    URL,
    _ask,
    _reply,
    _Script,
    _thread,
    _with_plan,
)
from tests.pg.test_office_actions import _staff

FEEDBACK = "/api/v1/office/assistant-feedback"
DRAFT = TicketDraft(summary="Reklama hisobidan pul yechilmayapti, tekshirib bering.")


def _prepared(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, str], dict]:
    headers, _owner = _with_plan(client, db)
    script = _Script(
        calls=[("create_ticket", DRAFT)],
        words=["To'lov holatini ko'rdim, sababi menda ko'rinmayapti."],
    )
    turn = _ask(client, db, headers, monkeypatch, script, question="Pul yechilmayapti")
    return headers, turn


def test_skipping_brings_the_button_and_keeps_nothing(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, turn = _prepared(client, db, monkeypatch)
    frame = _reply(client, headers, "Fikrim yo'q", session=turn["session_id"])
    assert "Tushunarli" in frame["html"]
    assert frame["buttons"][0]["kind"] == "ticket"
    assert frame["buttons"][0]["state"] == "open"
    assert db.scalar(select(func.count()).select_from(AssistantFeedback)) == 0
    # Asked once: the next words are a question for the assistant again.
    later = _Script(words=["Yaxshi."])
    _ask(
        client,
        db,
        headers,
        monkeypatch,
        later,
        question="Yana bir savol",
        session=turn["session_id"],
    )
    assert later.asked, "the next question reaches the model"


def test_a_client_in_russian_is_asked_in_russian(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner = _with_plan(client, db)
    owner.language = "ru"
    db.commit()
    script = _Script(calls=[("create_ticket", DRAFT)], words=["Проверил."])
    turn = _ask(
        client, db, headers, monkeypatch, script, question="Деньги не списались"
    )
    asked = _thread(client, headers, turn["session_id"])["messages"][1]
    assert "что было не так в моих ответах?" in asked["text"]
    assert asked["replies"] == ["Нет замечаний"]
    frame = _reply(
        client, headers, "Ответы слишком длинные", session=turn["session_id"]
    )
    assert "Спасибо" in frame["html"]
    kept = db.scalar(select(AssistantFeedback))
    assert kept is not None and kept.language == "ru"


def test_the_office_reads_it_and_marks_it_read(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, turn = _prepared(client, db, monkeypatch)
    _reply(client, headers, "Javob juda umumiy edi", session=turn["session_id"])

    _, support = _staff(db, Role.SUPPORT, email="aziza@office.test")
    listed = client.get(FEEDBACK, headers=support)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["open"] == 1 and len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["feedback"] == "Javob juda umumiy edi"
    assert row["question"] == "Pul yechilmayapti"
    assert row["ticket_summary"] == DRAFT.summary
    assert "sababi menda ko'rinmayapti" in row["answer"]
    assert row["owner"]["id"]

    found = client.get(FEEDBACK, params={"q": "umumiy"}, headers=support).json()
    assert len(found["rows"]) == 1
    assert (
        client.get(FEEDBACK, params={"q": "yo'q so'z"}, headers=support).json()["rows"]
        == []
    )

    done = client.patch(
        f"{FEEDBACK}/{row['id']}", json={"status": "done"}, headers=support
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done" and done.json()["closed_at"]
    assert client.get(FEEDBACK, headers=support).json()["open"] == 0
    assert (
        len(
            client.get(FEEDBACK, params={"tab": "done"}, headers=support).json()["rows"]
        )
        == 1
    )

    _, sales = _staff(db, Role.SALES, email="sotuv@office.test")
    # The office hides a screen from a role it is not for, as Django did.
    assert client.get(FEEDBACK, headers=sales).status_code == 404
    assert client.get(FEEDBACK, headers=headers).status_code == 404


def test_a_new_question_in_between_ends_the_wait(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wait is only on the newest answer: once another answer followed,
    the client's words go to the assistant, not the office."""
    headers, turn = _prepared(client, db, monkeypatch)
    _reply(client, headers, "Fikrim yo'q", session=turn["session_id"])
    later = _Script(words=["Mana javob."])
    _ask(
        client,
        db,
        headers,
        monkeypatch,
        later,
        question="Boshqa narsa",
        session=turn["session_id"],
    )
    assert later.asked
    messages = _thread(client, headers, turn["session_id"])["messages"]
    assert [m["author"] for m in messages] == ["user", "ai", "user", "ai", "user", "ai"]
    assert db.scalar(select(func.count()).select_from(AssistantFeedback)) == 0
    assert URL
