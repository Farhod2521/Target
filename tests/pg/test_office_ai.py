"""The office's assistant: what it reads, who may ask, and the answer."""

import json
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from llmkit import LLMResult, ToolCall
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMPurpose
from app.modules.audit.models import LLMCall
from app.modules.backoffice.constants import Role
from app.modules.billing.services import start_trial
from app.modules.officeai.models import OfficeAiMessage, OfficeAiThread
from app.modules.officeai.selectors import facts
from app.modules.officeai.services.answer import answer_turn
from app.modules.officeai.services.ask import turn_payload
from core.chat.lookup_arguments import Nothing
from core.officeai.tools import CustomerQuery, Span
from tests.pg.conftest import sign_up
from tests.pg.test_office_actions import _staff

URL = "/api/v2/office/ai"


@dataclass
class _Stream:
    pieces: list[str]
    result: Any = None

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield from self.pieces


@dataclass
class _Script:
    calls: list[tuple[str, Any]] = field(default_factory=list)
    words: list[str] = field(default_factory=lambda: ["Hammasi ", "joyida."])
    asked: list[dict[str, Any]] = field(default_factory=list)
    seen: list[tuple[str, str, bool]] = field(default_factory=list)


def _claude(script: _Script) -> Callable[..., Any]:
    class Fake:
        def converse(self, **asked: Any) -> _Stream:
            script.asked.append(asked)
            run = asked["run_tool"]
            for index, (name, arguments) in enumerate(script.calls):
                out = run(ToolCall(id=f"t{index}", name=name, arguments=arguments))
                script.seen.append((name, out.text, out.is_error))
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


def _ask(
    client: TestClient,
    db: Session,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    script: _Script,
    **body: Any,
) -> dict[str, Any]:
    monkeypatch.setattr("app.modules.officeai.services.answer.claude", _claude(script))
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


def _frames(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def _customers(client: TestClient, db: Session) -> list[User]:
    sign_up(client, email="birinchi@example.com")
    sign_up(client, email="ikkinchi@example.com")
    people = list(
        db.scalars(select(User).where(User.is_staff.is_(False)).order_by(User.email))
    )
    start_trial(db, user=people[0], now=utcnow())
    db.commit()
    return people


def test_the_figures_are_the_offices_own_and_staff_are_never_counted(
    client: TestClient, db: Session
) -> None:
    _customers(client, db)
    _staff(db, Role.SUPPORT, email="aziza@office.test")
    now = utcnow()

    summary = facts.customers_summary(db, span=Span(period="today"), now=now)
    assert "- Customers in all (staff never counted): 2" in summary
    assert "- Signed up in the window: 2" in summary
    assert "- On a trial now: 1" in summary
    assert "### Sign-ups per day" in summary

    plans = facts.plans_summary(db, now=now)
    assert "- In all now: 1 on trial, 0 paying" in plans

    trial = facts.customer_list(db, query=CustomerQuery(state="trial"), now=now)
    assert "## Customers matched: 1" in trial
    assert "birinchi@example.com" in trial and "(trial)" in trial
    never = facts.customer_list(db, query=CustomerQuery(term="ikkinchi"), now=now)
    assert "never had a plan" in never

    week = facts.money_summary(db, span=Span(period="7"), now=now)
    assert "- Payments: 0" in week
    assert "Window:" in facts.platform_activity(
        db, span=Span(period="month"), now=now, sees_money=False
    )
    assert "AI cost" not in facts.platform_activity(
        db, span=Span(period="month"), now=now, sees_money=False
    )
    assert "## Waiting on a person now" in facts.waiting_now(db, now=now)


def test_an_admin_asks_and_the_answer_quotes_only_what_was_read(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    _customers(client, db)
    _member, headers = _staff(db, Role.OWNER, email="ega@office.test")
    script = _Script(
        calls=[("customers_summary", Span(period="today"))],
        words=[
            "Bugun 2 kishi ro'yxatdan o'tdi, ",
            "va 1234 kishi to'lov qildi.",
        ],
    )

    turn = _ask(client, db, headers, monkeypatch, script, question="Bugun nechta?")
    assert any(name.endswith("answer_office_turn") for name, _ in queued)

    asked = script.asked[0]
    assert {tool.name for tool in asked["tools"]} >= {"money_summary", "customer_list"}
    assert "office assistant" in asked["system"]
    assert "Sees money: yes" in asked["system_tail"]
    assert "Signed up in the window: 2" in script.seen[0][1]

    token = headers["Authorization"].removeprefix("Bearer ")
    last = _frames(client.get(f"{URL}/stream/{turn['turn_id']}?token={token}").text)[-1]
    assert last["done"] is True and last["masked"] == 1
    assert "2 kishi" in last["html"] and "1234" not in last["html"]
    assert "[?]" in last["html"]

    screen = client.get(f"{URL}/threads/{turn['thread_id']}", headers=headers).json()
    assert [m["author"] for m in screen["messages"]] == ["user", "ai"]
    answer = screen["messages"][1]
    assert answer["status"] == "done"
    assert answer["meta"] == {"lookups": ["customers_summary"]}
    assert screen["threads"][0]["title"] == "Bugun nechta?"
    assert screen["questions_left"] == screen["questions_total"] - 1
    assert (
        db.scalar(
            select(func.count())
            .select_from(LLMCall)
            .where(LLMCall.purpose == LLMPurpose.OFFICE)
        )
        == 1
    )

    # The next question in the thread carries the earlier turn.
    second = _Script(words=["Ha."])
    _ask(
        client,
        db,
        headers,
        monkeypatch,
        second,
        question="Kecha-chi?",
        thread=turn["thread_id"],
    )
    assert [role for role, _ in second.asked[0]["history"]] == ["user", "assistant"]


def test_support_and_finance_do_not_open_it(
    client: TestClient, db: Session, queued: list
) -> None:
    for role, email in (
        (Role.SUPPORT, "aziza@office.test"),
        (Role.FINANCE, "m@o.test"),
    ):
        _member, headers = _staff(db, role, email=email)
        assert client.get(URL, headers=headers).status_code == 404
        asked = client.post(f"{URL}/ask", json={"question": "?"}, headers=headers)
        assert asked.status_code == 404
    assert queued == []


def test_a_turn_without_money_offers_no_money_look_ups(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate stays, for a turn that says it does not see money."""
    _member, headers = _staff(db, Role.OWNER, email="ega@office.test")
    script = _Script(calls=[("money_summary", Span()), ("recent_payments", Nothing())])
    monkeypatch.setattr(
        "app.modules.officeai.routers._sees_money", lambda db, user: False
    )

    _ask(client, db, headers, monkeypatch, script, question="Qancha pul tushdi?")

    names = {tool.name for tool in script.asked[0]["tools"]}
    assert "money_summary" not in names and "recent_payments" not in names
    assert "Sees money: no" in script.asked[0]["system_tail"]
    assert all(
        is_error and "does not see money" in text for _, text, is_error in script.seen
    )


def test_only_the_office_admins_open_it_and_each_sees_their_own(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner, owner = _staff(db, Role.OWNER, email="ega@office.test")
    _other, other = _staff(db, Role.OWNER, email="ikkinchi-ega@office.test")
    _support, support = _staff(db, Role.SUPPORT, email="aziza@office.test")
    _seller, seller = _staff(db, Role.SALES, email="sotuv@office.test")
    customer = sign_up(client)

    assert client.get(URL, headers=seller).status_code == 404
    assert client.get(URL, headers=support).status_code == 404
    assert client.get(URL, headers=customer).status_code in (401, 403, 404)
    assert (
        client.post(f"{URL}/ask", json={"question": "?"}, headers=seller).status_code
        == 404
    )
    empty = client.get(URL, headers=owner).json()
    assert empty["sees_money"] is True and empty["suggestions"]

    turn = _ask(client, db, owner, monkeypatch, _Script(), question="Holat qanday?")
    pk = turn["thread_id"]
    assert client.get(f"{URL}/threads/{pk}", headers=other).status_code == 404
    token = other["Authorization"].removeprefix("Bearer ")
    denied = _frames(client.get(f"{URL}/stream/{turn['turn_id']}?token={token}").text)
    assert denied[-1]["error"] == "denied"
    assert client.post(f"{URL}/stop/{turn['turn_id']}", headers=other).json() == {
        "stopped": False
    }
    assert client.delete(f"{URL}/threads/{pk}", headers=other).status_code == 404

    renamed = client.patch(
        f"{URL}/threads/{pk}", json={"title": "  Haftalik   holat "}, headers=owner
    )
    assert renamed.status_code == 200 and renamed.json()["title"] == "Haftalik holat"
    assert client.delete(f"{URL}/threads/{pk}", headers=owner).status_code == 204
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(OfficeAiThread)) == 0
    assert db.scalar(select(func.count()).select_from(OfficeAiMessage)) == 0


def test_a_stopped_question_costs_nothing_and_the_day_has_a_ceiling(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    _member, headers = _staff(db, Role.OWNER, email="ega@office.test")
    script = _Script()
    monkeypatch.setattr("app.modules.officeai.services.answer.claude", _claude(script))
    turn = client.post(f"{URL}/ask", json={"question": "Nega?"}, headers=headers).json()
    assert client.post(f"{URL}/stop/{turn['turn_id']}", headers=headers).json() == {
        "stopped": True
    }
    payload = turn_payload(turn_id=turn["turn_id"])
    assert payload is not None
    answer_turn(db, turn_id=turn["turn_id"], payload=payload, now=utcnow())
    db.commit()
    assert script.asked == []
    assert db.scalar(select(func.count()).select_from(LLMCall)) == 0

    monkeypatch.setattr("app.modules.officeai.services.ask.QUESTIONS_PER_DAY", 1)
    _ask(client, db, headers, monkeypatch, _Script(), question="Birinchi")
    spent = client.post(f"{URL}/ask", json={"question": "Ikkinchi"}, headers=headers)
    assert spent.status_code == 429
    assert spent.json()["code"] == "office_ai_spent"
    assert client.post(
        f"{URL}/ask", json={"question": "   "}, headers=headers
    ).status_code in (400, 429)


def test_the_owners_bot_asks_the_same_assistant_and_answers_in_the_chat(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.common.config import settings
    from app.modules.notifications.services import owners_respond
    from app.modules.officeai.services import telegram
    from app.modules.officeai.services.telegram import answer_in_telegram
    from tests.pg.test_office_telegram import FakeBot, _text

    owner_id = "5550001"
    _customers(client, db)
    boss, _headers = _staff(db, Role.OWNER, email="ega@office.test", superuser=True)
    bot = FakeBot()

    @contextmanager
    def opened():  # type: ignore[no-untyped-def]
        yield bot

    monkeypatch.setattr(owners_respond, "owners_bot", opened)
    monkeypatch.setattr("app.modules.notifications.bot.owners_bot", opened)
    monkeypatch.setattr(settings, "staff_bot_admin_ids", [owner_id])
    script = _Script(
        calls=[("customers_summary", Span(period="today"))],
        words=["**Bugun 2 kishi** ro'yxatdan o'tdi.\n\n- trialda: 1"],
    )
    monkeypatch.setattr("app.modules.officeai.services.answer.claude", _claude(script))

    said = owners_respond.handle_owners_update(
        db, payload=_text(owner_id, "Bugun nechta odam?"), now=utcnow()
    )
    assert said == "asked"
    assert bot.texts() == ["⏳ Ma'lumotlarni o'qiyapman…"]
    ((_name, (turn_id, chat_id, notice_id)),) = [
        item for item in queued if item[0].endswith("answer_office_turn_in_telegram")
    ]

    assert (
        answer_in_telegram(
            db, turn_id=turn_id, chat_id=chat_id, notice_id=notice_id, now=utcnow()
        )
        == "answered"
    )
    db.commit()
    edited = [f for called, f in bot.calls if called == "edit_message_text"]
    assert edited[0]["message_id"] == notice_id
    assert (
        "<b>Bugun 2 kishi</b>" in edited[0]["text"]
        and "• trialda: 1" in edited[0]["text"]
    )
    assert "Channel: Telegram" in script.asked[0]["system_tail"]
    thread = db.scalar(select(OfficeAiThread))
    assert thread is not None and thread.staff_id == boss.id

    # The next question goes on the same thread; /yangi starts another.
    owners_respond.handle_owners_update(
        db, payload=_text(owner_id, "Kecha-chi?"), now=utcnow()
    )
    assert db.scalar(select(func.count()).select_from(OfficeAiThread)) == 1
    owners_respond.handle_owners_update(
        db, payload=_text(owner_id, "/yangi"), now=utcnow()
    )
    owners_respond.handle_owners_update(
        db, payload=_text(owner_id, "Yana savol"), now=utcnow()
    )
    assert db.scalar(select(func.count()).select_from(OfficeAiThread)) == 2

    # Somebody not on the list asks nothing.
    assert (
        owners_respond.handle_owners_update(
            db, payload=_text("777", "Qancha pul tushdi?"), now=utcnow()
        )
        == "refused"
    )
    assert telegram.split("a" * 9000, size=4000) == ["a" * 4000, "a" * 4000, "a" * 1000]
