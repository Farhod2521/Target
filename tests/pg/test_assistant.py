"""The one chat against PostgreSQL (``/api/v2/assistant``).

A question is answered and streamed in pieces; the assistant checks the
account and prepares a ticket; the client presses it and Support gets it in
their chat, on their board and in Telegram; a person's reply comes back into
the same thread; a client with no plan still reaches a person; a visitor
leaves a phone; the office writes the known fixes the assistant searches.
The old ``/api/v1/chat`` is not touched by any of it.
"""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from llmkit import LLMResult, ToolCall
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.assistant.models import (
    AssistantMessage,
    AssistantSession,
    HelpArticle,
)
from app.modules.assistant.services import support
from app.modules.assistant.services.answer import answer_turn
from app.modules.assistant.services.ask import turn_payload
from app.modules.backoffice.constants import Role
from app.modules.billing.services import start_trial
from app.modules.boards.models import BoardCard
from app.modules.chat.models import ChatMessage, ChatSession
from app.modules.supportchat.models import (
    SupportConversation,
    SupportGuestChat,
    SupportGuestMessage,
    SupportMessage,
)
from core.assistant.tools import TicketDraft
from core.chat.lookup_arguments import Nothing
from tests.pg.conftest import sign_up
from tests.pg.test_office_actions import _staff
from tests.pg.test_supportchat import PNG, _auth, _user

URL = "/api/v2/assistant"
OFFICE = "/api/v1/office/support"


@pytest.fixture(autouse=True)
def media_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return tmp_path


# -- a model that answers from a script -------------------------------------


@dataclass
class _Stream:
    pieces: list[str]
    result: Any = None

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield from self.pieces


@dataclass
class _Script:
    """What the fake model does: tools to call, then the words."""

    calls: list[tuple[str, Any]] = field(default_factory=list)
    words: list[str] = field(default_factory=lambda: ["Hammasi ", "joyida."])
    asked: list[dict[str, Any]] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)


def _claude(script: _Script) -> Callable[..., Any]:
    class Fake:
        def converse(self, **asked: Any) -> _Stream:
            script.asked.append(asked)
            run = asked["run_tool"]
            for index, (name, arguments) in enumerate(script.calls):
                out = run(ToolCall(id=f"t{index}", name=name, arguments=arguments))
                script.seen.append(out.text)
            return _Stream(
                pieces=list(script.words),
                result=LLMResult(
                    value="".join(script.words),
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

    @contextmanager
    def factory(**_: Any):  # type: ignore[no-untyped-def]
        yield Fake()

    return factory


def _with_plan(
    client: TestClient, db: Session, **extra: str
) -> tuple[dict[str, str], User]:
    headers = sign_up(client, **extra)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    start_trial(db, user=owner, now=utcnow())
    db.commit()
    return headers, owner


def _ask(
    client: TestClient,
    db: Session,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    script: _Script,
    **body: Any,
) -> dict[str, Any]:
    monkeypatch.setattr("app.modules.assistant.services.answer.claude", _claude(script))
    turn = client.post(
        f"{URL}/ask", json={"question": "Savol", **body}, headers=headers
    )
    assert turn.status_code == 200, turn.text
    payload = turn_payload(turn_id=turn.json()["turn_id"])
    assert payload is not None
    answer_turn(db, turn_id=turn.json()["turn_id"], payload=payload, now=utcnow())
    db.commit()
    db.expire_all()
    return turn.json()


def _thread(client: TestClient, headers: dict[str, str], pk: str) -> dict[str, Any]:
    found = client.get(f"{URL}/threads/{pk}", headers=headers)
    assert found.status_code == 200, found.text
    return found.json()


def _frames(text: str) -> list[dict[str, Any]]:
    import json

    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


# -- the tests --------------------------------------------------------------


def test_a_question_is_answered_streamed_in_pieces_and_kept(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner = _with_plan(client, db)
    script = _Script(words=["Reklamangiz ", "ishlayapti, ", "hammasi joyida."])

    turn = _ask(client, db, headers, monkeypatch, script, question="Reklamam qanday?")
    assert any(name.endswith("answer_assistant_turn") for name, _ in queued)

    asked = script.asked[0]
    # The base is cached; the language is a name; the Context is in the tail.
    assert "Uzbek" in asked["system"] and "{{ language }}" not in asked["system"]
    assert "## Context" in asked["system_tail"]
    assert {tool.name for tool in asked["tools"]} >= {"account_health", "create_ticket"}

    token = headers["Authorization"].removeprefix("Bearer ")
    frames = _frames(client.get(f"{URL}/stream/{turn['turn_id']}?token={token}").text)
    assert frames[-1]["done"] is True
    assert "hammasi joyida" in frames[-1]["html"]
    assert "".join(frame["delta"] for frame in frames) == (
        "Reklamangiz ishlayapti, hammasi joyida."
    )
    assert (
        _frames(client.get(f"{URL}/stream/{turn['turn_id']}").text)[-1]["error"]
        == "denied"
    )

    thread = _thread(client, headers, turn["session_id"])
    assert [m["author"] for m in thread["messages"]] == ["user", "ai"]
    assert thread["messages"][1]["status"] == "done"
    assert thread["mode"] == "ai"
    # The old chat has nothing of it.
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 0


def test_a_ticket_is_prepared_pressed_and_lands_on_the_board_and_in_support(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner = _with_plan(client, db)
    script = _Script(
        calls=[
            ("account_health", Nothing()),
            (
                "create_ticket",
                TicketDraft(
                    summary="Kartadan pul yechildi, tarif ochilmadi.",
                    checked=["Tarif: faol", "Facebook: ulangan"],
                ),
            ),
        ],
        words=["Pul yechilgan, lekin hisob ochilmagan. ", "Tugma orqali yuboring."],
    )
    turn = _ask(client, db, headers, monkeypatch, script, question="Pulim yechildi")

    assert script.seen[0].startswith("How to read this:")
    assert "## Plan and payments" in script.seen[0]
    assert "nothing has been sent" in script.seen[1]
    # Prepared is not sent: nothing reached Support yet.
    assert db.scalar(select(SupportMessage.id)) is None

    thread = _thread(client, headers, turn["session_id"])
    answer = thread["messages"][1]
    ticket = answer["buttons"][0]
    assert ticket["kind"] == "ticket" and ticket["state"] == "open"
    assert ticket["label"] == "Mutaxassisga yuborish"

    pressed = client.post(
        f"{URL}/buttons/{answer['id']}/{ticket['key']}", headers=headers
    )
    assert pressed.status_code == 200, pressed.text
    assert pressed.json()["state"] == "sent"

    sent = db.scalar(select(SupportMessage))
    assert sent is not None and sent.source == "ai_chat"
    assert "Kartadan pul yechildi" in sent.body
    assert "Mijoz savoli: Pulim yechildi" in sent.body
    assert "• Tarif: faol" in sent.body
    assert any(name.endswith("deliver_support_question_task") for name, _ in queued)
    card = db.scalar(select(BoardCard).where(BoardCard.owner_id == owner.id))
    assert card is not None and card.column_code == "new"
    assert [reason["code"] for reason in card.reasons] == ["ai"]

    # Pressed twice is still one ticket.
    again = client.post(
        f"{URL}/buttons/{answer['id']}/{ticket['key']}", headers=headers
    )
    assert again.json()["state"] == "sent"
    assert db.scalar(select(func.count()).select_from(SupportMessage)) == 1

    # The question was in the thread already: the ticket adds no row.
    thread = _thread(client, headers, turn["session_id"])
    assert [m["author"] for m in thread["messages"]] == ["user", "ai"]
    assert thread["mode"] == "support"
    assert thread["support"]["thread_id"] == turn["session_id"]

    _, office = _staff(db, Role.SUPPORT, email="aziza@office.test")
    reply = client.post(
        f"{OFFICE}/{sent.conversation_id}/messages",
        data={"body": "Pul qaytarildi, tarif ochildi."},
        headers=office,
    )
    assert reply.status_code == 201, reply.text

    thread = _thread(client, headers, turn["session_id"])
    assert [m["author"] for m in thread["messages"]] == ["user", "ai", "staff"]
    staff = thread["messages"][2]
    assert staff["text"] == "Pul qaytarildi, tarif ochildi."
    assert staff["meta"]["author"] and staff["support"]["who"]
    assert thread["mode"] == "support"
    assert thread["support"]["unread"] is False  # opening the thread read it

    # The board moves, and the button says so.
    card.column_code = "in_progress"
    db.commit()
    state = client.get(f"{URL}/buttons/{answer['id']}/{ticket['key']}", headers=headers)
    assert state.json()["state"] == "working"

    # The assistant reads the person's reply next time.
    later = _Script(words=["Yaxshi."])
    _ask(
        client,
        db,
        headers,
        monkeypatch,
        later,
        question="Rahmat",
        session=turn["session_id"],
    )
    history = later.asked[0]["history"]
    assert history[-1][0] == "assistant"
    # The answer and the person's reply are one side's turn, joined.
    assert "\n\n[Support xodimi yozdi]\nPul qaytarildi" in history[-1][1]


def test_words_for_a_person_with_a_file_and_the_edit_and_delete_follow(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, _owner = _with_plan(client, db)
    sent = client.post(
        f"{URL}/support",
        data={"body": "Chek ilovada"},
        files={"attachments": ("chek.png", PNG, "image/png")},
        headers=headers,
    )
    assert sent.status_code == 201, sent.text
    row = sent.json()["message"]
    assert row["author"] == "user" and row["to_support"] is True
    assert [f["name"] for f in row["support"]["files"]] == ["chek.png"]
    session_id = sent.json()["session_id"]
    assert _thread(client, headers, session_id)["thread"]["title"] == "Yordam"
    question = db.scalar(select(SupportMessage))
    assert question is not None
    assert not support.show(db, message=question, now=utcnow())  # once only

    _, office = _staff(db, Role.SUPPORT, email="aziza@office.test")
    reply = client.post(
        f"{OFFICE}/{question.conversation_id}/messages",
        data={"body": "Birinchi javob"},
        headers=office,
    ).json()["message"]
    edited = client.patch(
        f"{OFFICE}/messages/{reply['id']}", json={"body": "Tuzatilgan"}, headers=office
    )
    assert edited.status_code == 200, edited.text
    thread = _thread(client, headers, session_id)
    assert thread["messages"][1]["text"] == "Tuzatilgan"
    assert thread["messages"][1]["support"]["edited_at"] is not None

    mine = thread["messages"][0]["support"]["id"]
    gone = client.delete(f"/api/v1/support/messages/{mine}", headers=headers)
    assert gone.status_code == 200, gone.text
    thread = _thread(client, headers, session_id)
    assert [m["text"] for m in thread["messages"]] == ["Tuzatilgan"]


def test_a_client_with_no_plan_reaches_a_person_and_not_the_ai(
    client: TestClient, db: Session
) -> None:
    owner = _user(db, "noplan@test.uz")
    db.commit()
    headers = _auth(owner)

    screen = client.get(URL, headers=headers).json()
    assert screen["entitled"] is False and screen["mode"] == "support"
    refused = client.post(f"{URL}/ask", json={"question": "Salom"}, headers=headers)
    assert refused.status_code >= 400

    sent = client.post(
        f"{URL}/support", data={"body": "To'lov o'tmayapti"}, headers=headers
    )
    assert sent.status_code == 201, sent.text
    thread = _thread(client, headers, sent.json()["session_id"])
    assert [m["to_support"] for m in thread["messages"]] == [True]
    assert thread["mode"] == "support"


def test_the_composer_goes_back_to_the_ai_when_the_person_is_done(
    client: TestClient, db: Session
) -> None:
    headers, _owner = _with_plan(client, db)
    session_id = client.post(
        f"{URL}/support", data={"body": "Rahmat"}, headers=headers
    ).json()["session_id"]
    conversation = db.scalar(select(SupportConversation))
    assert conversation is not None
    _, office = _staff(db, Role.SUPPORT, email="aziza@office.test")
    assert _thread(client, headers, session_id)["mode"] == "support"

    assert (
        client.post(f"{OFFICE}/{conversation.id}/settle", headers=office).status_code
        == 200
    )
    assert _thread(client, headers, session_id)["mode"] == "ai"

    client.post(
        f"{OFFICE}/{conversation.id}/messages",
        data={"body": "Arzimaydi"},
        headers=office,
    )
    assert _thread(client, headers, session_id)["mode"] == "support"
    reply = db.scalar(
        select(AssistantMessage).where(AssistantMessage.author == "staff")
    )
    assert reply is not None
    reply.created_at = utcnow() - timedelta(hours=25)
    db.commit()
    assert _thread(client, headers, session_id)["mode"] == "ai"


def test_a_support_chat_from_before_is_brought_in_once_and_others_are_left_alone(
    client: TestClient, db: Session
) -> None:
    headers, owner = _with_plan(client, db)
    member, office = _staff(db, Role.SUPPORT, email="aziza@office.test")
    then = utcnow() - timedelta(days=2)
    conversation = SupportConversation(
        owner_id=owner.id,
        last_message_at=then,
        last_client_at=then,
        last_office_at=then,
    )
    db.add(conversation)
    db.flush()
    for minutes, sender, body in (
        (2, owner.id, "Eski savol"),
        (1, member.id, "Eski javob"),
    ):
        db.add(
            SupportMessage(
                owner_id=owner.id,
                conversation_id=conversation.id,
                sender_id=sender,
                body=body,
                created_at=then - timedelta(minutes=minutes),
            )
        )
    db.commit()

    # A reply written before the client opens the new chat is not copied:
    # they have no thread yet, and the old screen still shows it.
    client.post(
        f"{OFFICE}/{conversation.id}/messages",
        data={"body": "Yangi javob"},
        headers=office,
    )
    assert db.scalar(select(func.count()).select_from(AssistantMessage)) == 0

    screen = client.get(URL, headers=headers).json()
    assert [s["title"] for s in screen["sessions"]] == ["Yordam"]
    thread = _thread(client, headers, screen["support"]["thread_id"])
    assert [(m["author"], m["text"]) for m in thread["messages"]] == [
        ("user", "Eski savol"),
        ("staff", "Eski javob"),
        ("staff", "Yangi javob"),
    ]
    client.get(URL, headers=headers)
    assert db.scalar(select(func.count()).select_from(AssistantMessage)) == 3
    assert db.scalar(select(func.count()).select_from(AssistantSession)) == 1


def test_account_health_names_the_problem_and_its_fix(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.accounts.models import AccountBlock, BlockReason
    from app.modules.assistant.selectors.health import account_health
    from app.modules.chat.selectors.scope import current_page_scope

    _headers, owner = _with_plan(client, db)
    reason = BlockReason(name="Shubhali to'lov", message_uz="To'lov tekshirilmoqda")
    db.add(reason)
    db.flush()
    db.add(
        AccountBlock(
            owner_id=owner.id,
            reason_id=reason.id,
            shown_to_user=True,
            blocked_at=utcnow(),
        )
    )
    db.commit()

    text = account_health(
        db, owner=owner, scope=current_page_scope(db, owner=owner), now=utcnow()
    )
    assert "## Plan and payments" in text and "## Lead delivery" in text
    assert "PROBLEM: the account is blocked" in text
    assert "To'lov tekshirilmoqda" in text
    assert "PROBLEM: Facebook is not connected." in text
    assert "Fix: connect it on Ulanishlar" in text


def test_a_visitor_is_asked_for_a_phone_and_a_guest_chat_opens(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _Script(
        calls=[
            ("create_ticket", TicketDraft(summary="Kirish sahifasi xato beryapti."))
        ],
        words=["Ism va telefon qoldiring."],
    )
    monkeypatch.setattr("app.modules.assistant.services.answer.claude", _claude(script))
    turn = client.post(
        f"{URL}/ask", json={"question": "Kira olmayapman", "guest_id": "g"}
    )
    assert turn.status_code == 200, turn.text
    turn_id = turn.json()["turn_id"]
    payload = turn_payload(turn_id=turn_id)
    assert payload is not None
    answer_turn(db, turn_id=turn_id, payload=payload, now=utcnow())
    db.commit()

    assert {tool.name for tool in script.asked[0]["tools"]} == {
        "help_search",
        "create_ticket",
    }
    assert "## A visitor" in script.asked[0]["system_tail"]
    last = _frames(client.get(f"{URL}/stream/{turn_id}").text)[-1]
    assert last["buttons"][0]["kind"] == "guest_ticket"
    assert db.scalar(select(SupportGuestChat)) is None

    refused = client.post(
        f"{URL}/guest-ticket", json={"turn_id": turn_id, "name": "Ali", "phone": "12"}
    )
    assert refused.status_code == 422 and set(refused.json()["problems"]) == {"phone"}
    opened = client.post(
        f"{URL}/guest-ticket",
        json={"turn_id": turn_id, "name": "Ali", "phone": "+998901234567"},
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["token"]
    words = db.scalar(select(SupportGuestMessage.body))
    assert words is not None and "Kirish sahifasi xato beryapti." in words
    assert any(name.endswith("deliver_guest_question_task") for name, _ in queued)
    again = client.post(
        f"{URL}/guest-ticket",
        json={"turn_id": turn_id, "name": "Ali", "phone": "+998901234567"},
    )
    assert again.status_code == 404


def test_the_office_writes_an_article_and_the_assistant_finds_it(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, office = _staff(db, Role.SUPPORT, email="aziza@office.test")
    _, finance = _staff(db, Role.FINANCE, email="pul@office.test")
    url = "/api/v2/office/help-articles"
    article = {
        "code": "lead-telegram",
        "problem_uz": "Lidlar Telegram guruhga kelmayapti",
        "steps_uz": "Botni guruhga admin qilib qo'shing\nMijozlar sahifasida qayta ulang",
        "keywords": "lid, telegram, guruh",
        "is_published": True,
    }
    assert client.post(url, json=article, headers=finance).status_code == 404
    unpublishable = client.post(url, json={**article, "steps_uz": ""}, headers=office)
    assert unpublishable.status_code == 422
    made = client.post(url, json=article, headers=office)
    assert made.status_code == 201, made.text
    assert (
        client.post(url, json=article, headers=office).status_code == 422
    )  # code taken

    found = client.post(
        f"{url}/search", params={"q": "telegramga lidlar kelmayapti"}, headers=office
    )
    assert "1. Botni guruhga admin qilib qo'shing" in found.json()["result"]

    _headers, owner = _with_plan(client, db)
    from app.modules.assistant.services.answer import Desk
    from core.assistant.tools import HelpSearch
    from core.chat.verify import FigureGate

    desk = Desk(
        db=db,
        owner=owner,
        now=utcnow(),
        gate=FigureGate(allowed=frozenset()),
        language="uz",
    )
    out = desk(
        ToolCall(
            id="h",
            name="help_search",
            arguments=HelpSearch(query="lid telegram kelmayapti"),
        )
    )
    assert out.text.startswith("How to read this:")
    assert "Lidlar Telegram guruhga kelmayapti (the team's article)" in out.text

    pk = made.json()["id"]
    assert client.delete(f"{url}/{pk}", headers=office).status_code == 204
    assert db.scalar(select(HelpArticle.id)) is None


def test_account_health_reads_an_open_bill(client: TestClient, db: Session) -> None:
    from app.modules.assistant.selectors.health import account_health
    from app.modules.billing.constants import InvoiceStatus
    from app.modules.billing.models import Invoice, Subscription
    from app.modules.chat.selectors.scope import current_page_scope

    _headers, owner = _with_plan(client, db)
    plan_id = db.scalar(
        select(Subscription.plan_id).where(Subscription.owner_id == owner.id)
    )
    db.add(
        Invoice(
            owner_id=owner.id,
            number="TA-OPEN-1",
            plan_id=plan_id,
            amount_minor=29000000,
            currency="UZS",
            period_days=30,
            expires_at=utcnow(),
            status=InvoiceStatus.PENDING,
        )
    )
    db.commit()

    text = account_health(
        db, owner=owner, scope=current_page_scope(db, owner=owner), now=utcnow()
    )
    assert "PROBLEM: bill TA-OPEN-1" in text
    assert "it needs a person" in text


def test_a_change_button_reports_where_the_change_has_got_to(
    client: TestClient, db: Session
) -> None:
    from app.modules.assistant.services import buttons
    from app.modules.audit.constants import ActionStatus
    from app.modules.audit.models import ActionLog

    _headers, owner = _with_plan(client, db)
    log = ActionLog(
        owner_id=owner.id,
        target_level="campaign",
        target_external_id="120",
        action="pause",
        status=ActionStatus.PENDING,
        idempotency_key="assistant-test-1",
    )
    db.add(log)
    db.commit()
    item = {"kind": "change", "key": "P1", "state": "sent", "log_id": str(log.id)}

    assert buttons.drawn(db, owner=owner, item=item, now=utcnow()).state == "working"
    log.status = ActionStatus.APPLIED
    db.commit()
    done = buttons.drawn(db, owner=owner, item=item, now=utcnow())
    assert (done.state, done.text) == ("done", "Bajarildi.")
    gone = buttons.drawn(db, owner=owner, item={**item, "log_id": "x"}, now=utcnow())
    assert gone.state == "gone"
