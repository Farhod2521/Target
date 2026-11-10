"""An answer that could not help, against PostgreSQL: an owner's question
lands in their support chat and Support hears of it; a visitor leaves a
name and a phone and a guest chat opens with the question."""

from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
from llmkit import LLMResult
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.chat import services
from app.modules.chat.models import ChatMessage
from app.modules.supportchat.models import (
    SupportGuestChat,
    SupportGuestMessage,
    SupportMessage,
)
from core.chat.choices import HANDOFF_MARK
from tests.pg.conftest import sign_up
from tests.pg.test_chat import _account, _mirror, _Stream

SORRY = "Bu savolga aniq javob topa olmadim. Mutaxassisga yubordim."


class _Unsure:
    def _answer(self, **asked: Any) -> _Stream:
        text = [SORRY, f"\n{HANDOFF_MARK}\n"]
        return _Stream(
            pieces=text,
            result=LLMResult(
                value="".join(text),
                input_tokens=10,
                output_tokens=5,
                cost_micros=1,
                currency="USD",
                latency_ms=1,
                prompt_name=asked.get("prompt_name", ""),
                prompt_version=asked.get("prompt_version", ""),
                model="test",
            ),
        )

    def stream(self, **asked: Any) -> _Stream:
        return self._answer(**asked)

    def converse(self, **asked: Any) -> _Stream:
        return self._answer(**asked)


@contextmanager
def _claude(**_: Any):  # type: ignore[no-untyped-def]
    yield _Unsure()


def _answer(db: Session, turn_id: str) -> None:
    payload = services.turn_payload(turn_id=turn_id)
    assert payload is not None
    services.answer_turn(db, turn_id=turn_id, payload=payload, now=utcnow())
    db.commit()
    db.expire_all()


def test_an_owners_unanswered_question_goes_to_their_support_chat(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    headers = sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    monkeypatch.setattr("app.modules.chat.services.answer.claude", _claude)

    turn = client.post(
        "/api/v1/chat/ask",
        json={"question": "Kartam ikki marta yechildi"},
        headers=headers,
    ).json()
    _answer(db, turn["turn_id"])

    sent = db.scalar(select(SupportMessage))
    assert sent is not None and sent.source == "ai_chat"
    assert "Savol: Kartam ikki marta yechildi" in sent.body
    assert HANDOFF_MARK not in sent.body
    assert any(name.endswith("deliver_support_question_task") for name, _ in queued)

    answer = db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
    assert answer is not None and HANDOFF_MARK not in answer.text

    token = headers["Authorization"].removeprefix("Bearer ")
    streamed = client.get(f"/api/v1/chat/stream/{turn['turn_id']}?token={token}")
    assert '"handoff": "sent"' in streamed.text
    thread = client.get(f"/api/v1/chat/threads/{turn['session_id']}", headers=headers)
    assert thread.json()["messages"][-1]["handoff"] == "sent"


def test_a_visitor_leaves_a_phone_and_a_guest_chat_opens_with_the_question(
    client: TestClient, db: Session, queued: list, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("app.modules.chat.services.answer.claude", _claude)
    turn = client.post(
        "/api/v1/chat/ask",
        json={"question": "Ro'yxatdan o'ta olmayapman", "guest_id": "g"},
    ).json()
    _answer(db, turn["turn_id"])

    streamed = client.get(f"/api/v1/chat/stream/{turn['turn_id']}")
    assert '"handoff": "ask_phone"' in streamed.text
    assert db.scalar(select(SupportGuestChat)) is None

    refused = client.post(
        "/api/v1/chat/handoff",
        json={"turn_id": turn["turn_id"], "name": "Ali", "phone": "12"},
    )
    assert refused.status_code == 422 and set(refused.json()["problems"]) == {"phone"}

    opened = client.post(
        "/api/v1/chat/handoff",
        json={"turn_id": turn["turn_id"], "name": "Ali", "phone": "+998901234567"},
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["token"]
    chat = db.scalar(select(SupportGuestChat))
    assert chat is not None and chat.phone == "+998901234567" and chat.email == ""
    words = db.scalar(select(SupportGuestMessage.body))
    assert words is not None and "Savol: Ro'yxatdan o'ta olmayapman" in words
    assert any(name.endswith("deliver_guest_question_task") for name, _ in queued)

    again = client.post(
        "/api/v1/chat/handoff",
        json={"turn_id": turn["turn_id"], "name": "Ali", "phone": "+998901234567"},
    )
    assert again.status_code == 404
