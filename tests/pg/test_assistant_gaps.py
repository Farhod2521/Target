"""What the assistant could not answer reaches the office («Meta & AI»), the
office writes the ready answer, and what the office writes is put into the
other languages - for the assistant's answers and for Meta's refusals."""

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from llmkit import LLMResult, ToolCall
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.assistant.constants import GapStatus, Translation
from app.modules.assistant.models import AssistantGap, HelpArticle
from app.modules.assistant.services.answer import Desk
from app.modules.assistant.services.translate import (
    translate_article,
    translate_refusal,
)
from app.modules.backoffice.constants import Role
from app.modules.chat.models import RefusalAnswer
from core.agent.office_translation import (
    OfficeTranslation,
    TranslatedField,
    TranslatedLanguage,
)
from core.assistant.tools import GapReport, HelpSearch
from core.chat.verify import FigureGate
from tests.pg.test_assistant import _ask, _Script, _with_plan
from tests.pg.test_office_actions import _staff

GAPS = "/api/v2/office/assistant-gaps"
ARTICLES = "/api/v2/office/help-articles"
REFUSALS = "/api/v1/office/refusals"

MOVE = GapReport(
    topic="Reklamani boshqa akkauntga ko'chirish",
    kind="tool",
    missing="Kampaniyani boshqa reklama akkauntiga ko'chiradigan amal kerak.",
)


def _gaps(db: Session) -> list[AssistantGap]:
    db.expire_all()
    return list(db.scalars(select(AssistantGap).order_by(AssistantGap.created_at)))


# -- the assistant writes the list ---------------------------------------------


def test_what_the_assistant_reports_is_kept_once_and_counted(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner = _with_plan(client, db)
    script = _Script(calls=[("report_gap", MOVE)], words=["Buni qila olmayman."])

    _ask(client, db, headers, monkeypatch, script, question="Reklamani ko'chirib ber")
    again = GapReport(
        topic="Reklamani boshqa akkauntga ko'chirish mumkinmi",
        kind="tool",
        missing="Boshqa gap.",
    )
    _ask(
        client,
        db,
        headers,
        monkeypatch,
        _Script(calls=[("report_gap", again)]),
        question="Boshqa akkauntga o'tkazsa bo'ladimi?",
    )

    # The person is not told, and the note costs none of the look-ups.
    assert "not told" in script.seen[0]
    (row,) = _gaps(db)
    assert row.hits == 2 and row.kind == "tool" and row.status == GapStatus.OPEN
    assert row.missing == MOVE.missing
    assert row.question == "Boshqa akkauntga o'tkazsa bo'ladimi?"
    assert [item["owner_id"] for item in row.samples] == [str(owner.id)] * 2
    assert row.samples[1]["question"] == "Reklamani ko'chirib ber"


def test_a_search_that_found_nothing_is_kept_and_one_that_found_is_not(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner = _with_plan(client, db)
    db.add(
        HelpArticle(
            code="lead-telegram",
            problem_uz="Lidlar Telegram guruhga kelmayapti",
            steps_uz="Botni guruhga admin qiling",
            is_published=True,
        )
    )
    db.commit()

    found = _Script(calls=[("help_search", HelpSearch(query="lid telegram guruh"))])
    _ask(client, db, headers, monkeypatch, found, question="Lid kelmayapti")
    assert _gaps(db) == []

    nothing = _Script(
        calls=[("help_search", HelpSearch(query="chegirma kuponi qo'shish"))]
    )
    _ask(client, db, headers, monkeypatch, nothing, question="Kupon qanday qo'shaman?")
    answered = _Script(words=["Hammasi joyida."])
    _ask(client, db, headers, monkeypatch, answered, question="Salom")

    (row,) = _gaps(db)
    assert row.topic == "chegirma kuponi qo'shish" and row.kind == "answer"
    assert row.missing == "" and row.queries == ["chegirma kuponi qo'shish"]


def test_a_visitor_s_unanswered_question_is_kept_too(db: Session) -> None:
    from app.modules.assistant.services.answer import VISITOR_TOOLS, _note_gap

    assert "report_gap" in {tool.name for tool in VISITOR_TOOLS}
    desk = Desk(db=db, owner=None, now=utcnow(), gate=FigureGate(allowed=frozenset()))
    desk(ToolCall(id="g", name="report_gap", arguments=MOVE))
    desk(ToolCall(id="g2", name="report_gap", arguments=MOVE))

    _note_gap(
        db,
        payload={"question": "Ko'chirish", "language": "ru"},
        desk=desk,
        now=utcnow(),
    )
    db.commit()

    (row,) = _gaps(db)
    assert row.hits == 1 and row.language == "ru" and desk.made == 0


# -- the office reads it and writes the answer -----------------------------------


def _gap(db: Session, **fields: Any) -> AssistantGap:
    row = AssistantGap(
        **{
            "topic": "Chegirma kuponi qo'shish",
            "kind": "answer",
            "missing": "Promokod kiritish qadamlari yozilishi kerak.",
            "question": "Kupon qanday qo'shaman?",
            "queries": ["chegirma kuponi"],
            "samples": [
                {"question": "Kupon qanday qo'shaman?", "at": "", "owner_id": ""}
            ],
            **fields,
        }
    )
    db.add(row)
    db.commit()
    return row


def test_the_list_is_for_support_the_owner_and_the_developers(
    client: TestClient, db: Session
) -> None:
    _, sales = _staff(db, Role.SALES, email="sotuv@office.test")
    _, engineer = _staff(db, Role.ENGINEER, email="dev@office.test")
    _gap(db, hits=2)
    _gap(
        db,
        hits=9,
        topic="Hisobot yuklab olish",
        kind="tool",
        question="Hisobot kerak",
        missing="",
    )
    _gap(db, status=GapStatus.DISMISSED, topic="Ob-havo")

    assert client.get(GAPS, headers=sales).status_code == 404
    # The office screen reads it beside the refusals, on the first API too.
    assert client.get("/api/v1/office/assistant-gaps", headers=engineer).json()["open"] == 2
    assert client.get("/api/v1/office/help-articles", headers=engineer).json() == {"rows": []}
    page = client.get(GAPS, headers=engineer).json()
    closed = client.get(GAPS, params={"tab": "closed"}, headers=engineer).json()
    found = client.get(GAPS, params={"q": "kupon"}, headers=engineer).json()

    assert [row["topic"] for row in page["rows"]] == [
        "Hisobot yuklab olish",
        "Chegirma kuponi qo'shish",
    ]
    assert page["open"] == 2 and page["total"] == 2
    assert page["rows"][0]["kind_label"] == "Imkoniyat qo'shish kerak"
    assert [row["topic"] for row in closed["rows"]] == ["Ob-havo"]
    assert [row["hits"] for row in found["rows"]] == [2]
    # The Meta tab carries the count for those who may open this one.
    assert client.get(REFUSALS, headers=engineer).json()["ai_open"] == 2
    assert client.get(REFUSALS, headers=sales).json()["ai_open"] is None


def test_a_written_answer_is_found_by_the_assistant_and_translated(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, office = _staff(db, Role.SUPPORT, email="aziza@office.test")
    row = _gap(db)
    body = {
        "problem": "Promokodni qayerga kiritaman?",
        "steps": "1. «Tariflar» sahifasini oching\n2. «Promokod» maydoniga yozing",
    }

    assert (
        client.post(
            f"{GAPS}/{row.id}/answer", json={"problem": "P"}, headers=office
        ).status_code
        == 422
    )
    saved = client.post(f"{GAPS}/{row.id}/answer", json=body, headers=office)

    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert out["status"] == "answered" and out["article"]["is_published"] is True
    assert out["article"]["translation"] == "translating"
    assert out["article"]["code"].startswith("javob-")
    article_id = out["article"]["id"]
    assert (
        "app.modules.assistant.tasks.translate_article_task",
        (article_id, str(actor.id), "uz", ["ru", "en"]),
    ) in queued
    # The question's own words find it, though the answer names none of them.
    search = client.post(
        f"{ARTICLES}/search", params={"q": "chegirma kuponi"}, headers=office
    )
    assert "«Promokod» maydoniga yozing" in search.json()["result"]
    assert client.get(GAPS, headers=office).json()["open"] == 0

    _fake_claude(
        monkeypatch,
        ru={
            "problem": "Куда ввести промокод?",
            "steps": "1. Откройте «Tariflar»\n2. Введите в поле «Promokod»",
        },
        en={
            "problem": "Where do I enter a promo code?",
            "steps": "1. Open «Tariflar»\n2. Type it into «Promokod»",
        },
    )
    assert (
        translate_article(
            db,
            article_id=article_id,
            actor_id=str(actor.id),
            source="uz",
            targets=["ru", "en"],
        )
        == "ready"
    )
    db.expire_all()
    article = db.get(HelpArticle, article_id)
    assert article is not None and article.translation == Translation.NONE
    assert article.problem_ru == "Куда ввести промокод?"
    assert (
        article.steps_en.startswith("1. Open") and article.problem_uz == body["problem"]
    )

    # Changed again for the same question: the same article, not a second.
    client.post(
        f"{GAPS}/{row.id}/answer",
        json={**body, "problem": "Promokod kiritish", "translate": False},
        headers=office,
    )
    db.expire_all()
    assert [a.problem_uz for a in db.scalars(select(HelpArticle))] == [
        "Promokod kiritish"
    ]

    # Asked again and still not found: it waits for the office again.
    from app.modules.assistant.services.gaps import note_gap

    note_gap(
        db,
        question="Kupon?",
        language="uz",
        owner_id="",
        message_id="",
        report=None,
        searches=[("chegirma kuponi", 0)],
        now=utcnow(),
    )
    db.commit()
    reopened = client.get(GAPS, headers=office).json()["rows"][0]
    assert reopened["reopened"] is True and reopened["hits"] == 2

    # The answer deleted: nothing points at it any more.
    assert client.delete(f"{ARTICLES}/{article_id}", headers=office).status_code == 204
    db.expire_all()
    assert _gaps(db)[0].article_id is None


def test_a_question_is_dismissed_and_put_back(client: TestClient, db: Session) -> None:
    _, office = _staff(db, Role.OWNER, email="egasi@office.test")
    row = _gap(db)

    gone = client.patch(
        f"{GAPS}/{row.id}", json={"status": "dismissed"}, headers=office
    )
    assert gone.json()["status"] == "dismissed" and gone.json()["closed_at"]
    assert client.get(GAPS, headers=office).json()["rows"] == []
    back = client.patch(f"{GAPS}/{row.id}", json={"status": "open"}, headers=office)
    assert back.json()["status"] == "open" and back.json()["closed_at"] is None
    assert (
        client.patch(
            f"{GAPS}/{row.id}", json={"status": "answered"}, headers=office
        ).status_code
        == 422
    )


# -- the office's words in the other languages -------------------------------------


def _fake_claude(
    monkeypatch: pytest.MonkeyPatch, **languages: dict[str, str]
) -> list[str]:
    """A model that answers with these languages; what it was asked is returned."""
    asked: list[str] = []

    class Fake:
        def structured(self, **call: Any) -> LLMResult[OfficeTranslation]:
            asked.append(call["prompt"])
            return LLMResult(
                value=OfficeTranslation(
                    languages=[
                        TranslatedLanguage(
                            language=code,
                            fields=[
                                TranslatedField(name=name, text=text)
                                for name, text in fields.items()
                            ],
                        )
                        for code, fields in languages.items()
                    ]
                ),
                input_tokens=10,
                output_tokens=5,
                cost_micros=1,
                currency="USD",
                latency_ms=1,
                prompt_name=call.get("prompt_name", ""),
                prompt_version=call.get("prompt_version", ""),
                model="test",
            )

    @contextmanager
    def factory(**_: Any):  # type: ignore[no-untyped-def]
        yield Fake()

    monkeypatch.setattr("app.common.llm.claude", factory)
    return asked


UZ = "Akkauntda **to'lov usuli yo'q**.\n\n1. To'lov sahifasini oching: [[tolov]]\n2. Kartani qo'shing."
RU = "В аккаунте **нет способа оплаты**.\n\n1. Откройте страницу оплаты: [[tolov]]\n2. Добавьте карту."
EN = "The account has **no payment method**.\n\n1. Open the payment page: [[tolov]]\n2. Add a card."


def _refusal(db: Session, **fields: Any) -> RefusalAnswer:
    row = RefusalAnswer(
        key="meta:100/1359188", answer_uz="AI matni", prompt_version="v2", **fields
    )
    db.add(row)
    db.commit()
    return row


def test_an_edited_refusal_answer_is_written_in_the_other_languages(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, office = _staff(db, Role.SUPPORT, email="s@office.test")
    row = _refusal(db, answer_ru="Старый текст")

    saved = client.patch(
        f"{REFUSALS}/{row.id}",
        json={"answer_uz": UZ, "translate_from": "uz"},
        headers=office,
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["translation"] == "translating"
    # The office's own language is shown at once; the old Russian until then.
    assert (
        saved.json()["answer_uz"] == UZ and saved.json()["answer_ru"] == "Старый текст"
    )
    args = (str(row.id), str(actor.id), "uz", ["ru", "en"])
    assert ("app.modules.assistant.tasks.translate_refusal_task", args) in queued

    asked = _fake_claude(monkeypatch, ru={"answer": RU}, en={"answer": EN})
    assert (
        translate_refusal(
            db,
            answer_id=str(row.id),
            actor_id=str(actor.id),
            source="uz",
            targets=["ru", "en"],
        )
        == "ready"
    )

    assert "[[tolov]]" in asked[0] and "ru (Russian)" in asked[0]
    out = client.get(f"{REFUSALS}/{row.id}", headers=office).json()
    assert out["translation"] == "" and out["reviewed"] is True
    assert (out["answer_uz"], out["answer_ru"], out["answer_en"]) == (UZ, RU, EN)


def test_a_language_the_office_wrote_itself_is_not_translated_over(
    client: TestClient, db: Session, queued: list
) -> None:
    actor, office = _staff(db, Role.SUPPORT, email="s@office.test")
    row = _refusal(db)

    both = client.patch(
        f"{REFUSALS}/{row.id}",
        json={"answer_uz": UZ, "answer_ru": RU, "translate_from": "uz"},
        headers=office,
    )
    assert both.json()["translation"] == "translating"
    assert queued[-1][1] == (str(row.id), str(actor.id), "uz", ["en"])

    sent = len(queued)
    plain = client.patch(
        f"{REFUSALS}/{row.id}", json={"answer_uz": UZ + "!"}, headers=office
    )
    assert plain.json()["translation"] == "" and len(queued) == sent


def test_a_translation_that_lost_a_link_or_came_late_changes_nothing(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, office = _staff(db, Role.SUPPORT, email="s@office.test")
    row = _refusal(db)
    ask = {
        "answer_id": str(row.id),
        "actor_id": str(actor.id),
        "source": "uz",
        "targets": ["ru", "en"],
    }
    client.patch(
        f"{REFUSALS}/{row.id}",
        json={"answer_uz": UZ, "translate_from": "uz"},
        headers=office,
    )

    _fake_claude(
        monkeypatch, ru={"answer": RU.replace("[[tolov]]", "")}, en={"answer": EN}
    )
    assert translate_refusal(db, **ask) == "failed"
    out = client.get(f"{REFUSALS}/{row.id}", headers=office).json()
    assert (
        out["translation"] == "failed"
        and out["answer_ru"] == ""
        and out["answer_uz"] == UZ
    )
    assert translate_refusal(db, **ask) == "stale"

    # Saved again while the worker was away: the late answer is dropped.
    client.patch(
        f"{REFUSALS}/{row.id}",
        json={"answer_uz": UZ, "translate_from": "uz"},
        headers=office,
    )

    @contextmanager
    def late(**_: Any):  # type: ignore[no-untyped-def]
        class Edits:
            def structured(self, **call: Any) -> Any:
                fresh = db.get(RefusalAnswer, row.id)
                assert fresh is not None
                fresh.edited_at = utcnow()
                db.commit()
                return _result(ru={"answer": RU}, en={"answer": EN})

        yield Edits()

    monkeypatch.setattr("app.common.llm.claude", late)
    assert translate_refusal(db, **ask) == "stale"
    db.expire_all()
    assert db.get(RefusalAnswer, row.id).answer_ru == ""  # type: ignore[union-attr]


def _result(**languages: dict[str, str]) -> LLMResult[OfficeTranslation]:
    return LLMResult(
        value=OfficeTranslation(
            languages=[
                TranslatedLanguage(
                    language=code,
                    fields=[TranslatedField(name=n, text=t) for n, t in fields.items()],
                )
                for code, fields in languages.items()
            ]
        ),
        input_tokens=10,
        output_tokens=5,
        cost_micros=1,
        currency="USD",
        latency_ms=1,
        prompt_name="office_translation",
        prompt_version="v1",
        model="test",
    )


def test_a_translation_nobody_finished_reads_as_failed(
    client: TestClient, db: Session
) -> None:
    from datetime import timedelta

    _, office = _staff(db, Role.SUPPORT, email="s@office.test")
    row = _refusal(
        db,
        translation=Translation.TRANSLATING,
        edited_at=utcnow() - timedelta(minutes=30),
    )

    assert (
        client.get(f"{REFUSALS}/{row.id}", headers=office).json()["translation"]
        == "failed"
    )


def test_an_article_saved_in_russian_gets_its_uzbek_from_the_worker(
    client: TestClient, db: Session, queued: list
) -> None:
    actor, office = _staff(db, Role.SUPPORT, email="s@office.test")
    body = {
        "problem_ru": "Лиды не приходят",
        "steps_ru": "1. Подключите бота",
        "is_published": True,
    }

    assert client.post(ARTICLES, json=body, headers=office).status_code == 422
    made = client.post(ARTICLES, json={**body, "translate_from": "ru"}, headers=office)

    assert made.status_code == 201, made.text
    assert made.json()["translation"] == "translating"
    assert queued[-1][1] == (made.json()["id"], str(actor.id), "ru", ["uz", "en"])
    # Found in the language it has, until the others arrive.
    search = client.post(
        f"{ARTICLES}/search", params={"q": "лиды не приходят"}, headers=office
    )
    assert "Подключите бота" in search.json()["result"]
