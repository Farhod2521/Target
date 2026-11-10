"""So'rovnomalar in the office: writing, languages, life, results and filters."""

import uuid
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.models import Plan, Subscription
from app.modules.supportchat.models import SupportConversation
from app.modules.surveys.constants import SNOOZE_KEY, SurveyState
from app.modules.surveys.models import (
    Survey,
    SurveyQuestion,
    SurveyResponse,
    SurveySighting,
)
from app.modules.surveys.services.translate import translate_survey
from core.agent.survey_translation import (
    SurveyLanguage,
    SurveyTranslation,
    TranslatedQuestion,
)
from tests.pg.test_office_actions import _bearer, _shop, _staff

URL = "/api/v1/office/surveys"


def _body(**fields: Any) -> dict[str, Any]:
    return {
        "name": "Oktabr",
        "source_language": "uz",
        "title": "Fikringiz",
        "intro": "Ikki savol",
        "questions": [
            {
                "kind": "choice",
                "text": "Yoqdimi?",
                "options": ["Ha", "Yo'q"],
            },
            {
                "kind": "number",
                "text": "Baho",
                "min_value": 0,
                "max_value": 10,
            },
            {
                "kind": "text",
                "text": "Nega?",
                "is_required": False,
                "show_if": 1,
                "show_options": [1],
            },
        ],
        **fields,
    }


def _admin(db: Session) -> dict[str, str]:
    return _staff(db, Role.SUPPORT, email="support@office.test")[1]


def _translated(db: Session, survey_id: str) -> Survey:
    """Every language filled, as a finished translation leaves it."""
    db.expire_all()
    survey = db.get(Survey, survey_id)
    survey.title = {code: f"Sarlavha {code}" for code in ("uz", "ru", "en")}
    survey.intro = {code: f"Kirish {code}" for code in ("uz", "ru", "en")}
    for row in db.scalars(
        select(SurveyQuestion).where(SurveyQuestion.survey_id == survey.id)
    ):
        row.text = {code: f"S{row.position} {code}" for code in ("uz", "ru", "en")}
        row.options = [
            {code: f"V{index} {code}" for code in ("uz", "ru", "en")}
            for index, _ in enumerate(row.options)
        ]
    survey.state = SurveyState.READY
    db.commit()
    return survey


def _created(client: TestClient, headers: dict[str, str], **fields: Any) -> str:
    made = client.post(URL, headers=headers, json=_body(**fields))
    assert made.status_code == 200, made.text
    return made.json()["id"]


def _ready(
    client: TestClient, db: Session, headers: dict[str, str], **fields: Any
) -> Survey:
    return _translated(db, _created(client, headers, **fields))


def _customer(db: Session, plan: Plan, email: str, *, days: int = 30) -> User:
    person = User(email=email, full_name=email, password="!", date_joined=utcnow())
    db.add(person)
    db.flush()
    now = utcnow()
    db.add(
        Subscription(
            owner_id=person.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            started_at=now - timedelta(days=days),
            expires_at=now + timedelta(days=20),
        )
    )
    db.commit()
    return person


def _answer(db: Session, survey: Survey, owner: User, **said: Any) -> SurveyResponse:
    rows = list(
        db.scalars(
            select(SurveyQuestion)
            .where(SurveyQuestion.survey_id == survey.id)
            .order_by(SurveyQuestion.position)
        )
    )
    answers = []
    for row in rows:
        item = said.get(f"q{row.position}")
        if item is not None:
            answers.append({"question": str(row.id), **item})
    response = SurveyResponse(
        owner_id=owner.id,
        survey_id=survey.id,
        language=said.get("language", "uz"),
        channel=said.get("channel", "web"),
        answers=answers,
        created_at=said.get("at", utcnow()),
    )
    db.add(response)
    db.commit()
    return response


@pytest.mark.parametrize("role", [Role.SALES, Role.ENGINEER])
def test_a_role_outside_the_admins_gets_a_missing_page(
    client: TestClient, db: Session, role: Role
) -> None:
    _, headers = _staff(db, role, email="member@office.test")
    assert client.get(URL, headers=headers).status_code == 404
    assert client.post(URL, headers=headers, json=_body()).status_code == 404
    assert client.get(f"{URL}/roster", headers=headers).status_code == 404
    assert client.get(f"{URL}/responses", headers=headers).status_code == 404


def test_a_customer_gets_a_missing_page(client: TestClient, db: Session) -> None:
    shop, _ = _shop(db)
    assert client.get(URL, headers=_bearer(shop)).status_code == 404


def test_saving_writes_the_questions_and_asks_for_a_translation(
    client: TestClient, db: Session, queued: list[Any]
) -> None:
    headers = _admin(db)
    survey_id = _created(client, headers, ask_after_days=14)

    one = client.get(f"{URL}/{survey_id}", headers=headers).json()

    assert one["state"] == "translating" and one["phase"] == "draft"
    assert one["ask_after_days"] == 14
    assert [q["position"] for q in one["questions"]] == [1, 2, 3]
    # The boards mark a question's options by its id (help-options).
    assert all(uuid.UUID(q["id"]) for q in one["questions"])
    assert one["questions"][2]["show_if"] == 1
    assert one["questions"][2]["show_options"] == [1]
    assert one["questions"][2]["is_required"] is False
    assert one["tabs"][0] == {"code": "uz", "source": True, "filled": True}
    assert [tab["filled"] for tab in one["tabs"][1:]] == [False, False]
    assert any("translate_survey" in name for name, _ in queued)
    row = client.get(URL, headers=headers).json()[0]
    assert row["questions"] == 3 and row["answers"] == 0


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"questions": []}, "questions"),
        ({"name": "   "}, "name"),
        ({"title": "   "}, "title"),
        ({"source_language": "fr"}, "source_language"),
        ({"questions": [{"kind": "text", "text": ""}]}, "questions.0"),
        (
            {"questions": [{"kind": "choice", "text": "x", "options": ["a"]}]},
            "questions.0",
        ),
        (
            {"questions": [{"kind": "choice", "text": "x", "options": ["a", "A"]}]},
            "questions.0",
        ),
        (
            {
                "questions": [
                    {"kind": "number", "text": "x", "min_value": 5, "max_value": 5}
                ]
            },
            "questions.0",
        ),
        (
            {
                "questions": [
                    {"kind": "number", "text": "x", "min_value": 0, "max_value": 11}
                ]
            },
            "questions.0",
        ),
        (
            {
                "questions": [
                    {"kind": "text", "text": "x", "show_if": 1, "show_options": [0]}
                ]
            },
            "questions.0",
        ),
        (
            {
                "questions": [
                    {"kind": "text", "text": "x"},
                    {"kind": "text", "text": "y", "show_if": 1, "show_options": [0]},
                ]
            },
            "questions.1",
        ),
        (
            {
                "starts_at": "2030-01-02T00:00:00Z",
                "ends_at": "2030-01-01T00:00:00Z",
            },
            "ends_at",
        ),
    ],
)
def test_a_bad_survey_is_refused_under_its_field(
    client: TestClient, db: Session, change: dict[str, Any], field: str
) -> None:
    headers = _admin(db)
    refused = client.post(URL, headers=headers, json=_body(**change))
    assert refused.status_code == 422, refused.text
    assert field in refused.json()["problems"]
    assert db.scalar(select(func.count(Survey.id))) == 0


def test_eleven_questions_are_refused(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    many = [{"kind": "text", "text": f"S{n}"} for n in range(11)]
    refused = client.post(URL, headers=headers, json=_body(questions=many))
    assert refused.status_code == 422


def test_a_new_name_keeps_the_translations_and_new_words_replace_them(
    client: TestClient, db: Session, queued: list[Any]
) -> None:
    headers = _admin(db)
    survey = _ready(client, db, headers)
    same = client.get(f"{URL}/{survey.id}", headers=headers).json()
    body = _body(
        title=same["title"],
        intro=same["intro"],
        name="Yangi nom",
        questions=[
            {
                "kind": q["kind"],
                "text": q["text"],
                "options": q["options"],
                "allows_many": q["allows_many"],
                "min_value": q["min_value"],
                "max_value": q["max_value"],
                "is_required": q["is_required"],
                "show_if": q["show_if"],
                "show_options": q["show_options"],
            }
            for q in same["questions"]
        ],
        ask_after_days=3,
    )
    queued.clear()

    saved = client.put(f"{URL}/{survey.id}", headers=headers, json=body)

    assert saved.status_code == 200, saved.text
    db.expire_all()
    kept = db.get(Survey, survey.id)
    assert kept.name == "Yangi nom" and kept.ask_after_days == 3
    assert kept.state == SurveyState.READY and kept.title["ru"] == "Sarlavha ru"
    assert not queued

    body["title"] = "Boshqa sarlavha"
    client.put(f"{URL}/{survey.id}", headers=headers, json=body)
    db.expire_all()
    changed = db.get(Survey, survey.id)
    assert changed.state == SurveyState.TRANSLATING
    assert changed.title == {"uz": "Boshqa sarlavha"}
    assert queued


def test_a_translating_survey_refuses_a_save(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    survey_id = _created(client, headers)
    refused = client.put(f"{URL}/{survey_id}", headers=headers, json=_body())
    assert refused.status_code == 400
    assert refused.json()["code"] == "survey_is_translating"


def test_publishing_needs_every_language_and_stopping_keeps_the_answers(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    survey_id = _created(client, headers)
    early = client.post(f"{URL}/{survey_id}/publish", headers=headers)
    assert early.status_code == 400 and early.json()["code"] == "survey_not_ready"

    _translated(db, survey_id)
    done = client.post(f"{URL}/{survey_id}/publish", headers=headers)
    assert done.status_code == 200, done.text
    assert client.get(f"{URL}/{survey_id}", headers=headers).json()["phase"] == "live"

    stopped = client.post(f"{URL}/{survey_id}/stop", headers=headers)
    assert stopped.status_code == 200
    assert client.get(f"{URL}/{survey_id}", headers=headers).json()["phase"] == "closed"


def test_a_live_or_answered_survey_keeps_its_questions_and_is_not_deleted(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    _, plan = _shop(db)
    person = _customer(db, plan, "a@client.test")
    survey = _ready(client, db, headers)
    client.post(f"{URL}/{survey.id}/publish", headers=headers)

    live = client.put(f"{URL}/{survey.id}", headers=headers, json=_body(title="Yangi"))
    assert live.status_code == 400 and live.json()["code"] == "survey_is_live"
    assert client.post(f"{URL}/{survey.id}/delete", headers=headers).status_code == 400
    assert (
        client.post(f"{URL}/{survey.id}/retranslate", headers=headers).status_code
        == 400
    )

    client.post(f"{URL}/{survey.id}/stop", headers=headers)
    _answer(db, survey, person, q2={"number": 9})
    closed = client.put(
        f"{URL}/{survey.id}", headers=headers, json=_body(title="Yangi")
    )
    assert closed.status_code == 400 and closed.json()["code"] == "survey_has_answers"
    gone = client.post(f"{URL}/{survey.id}/delete", headers=headers)
    assert gone.status_code == 400 and gone.json()["code"] == "survey_has_answers"


def test_deleting_removes_the_survey_and_its_rows(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    shop, _ = _shop(db)
    survey = _ready(client, db, headers)
    db.add(SurveySighting(survey_id=survey.id, owner_id=shop.id))
    db.commit()

    done = client.post(f"{URL}/{survey.id}/delete", headers=headers)

    assert done.status_code == 200, done.text
    assert client.get(f"{URL}/{survey.id}", headers=headers).status_code == 404
    assert db.scalar(select(func.count(SurveyQuestion.id))) == 0
    assert db.scalar(select(func.count(SurveySighting.id))) == 0


def test_a_copy_keeps_every_language_and_is_closed(
    client: TestClient, db: Session, queued: list[Any]
) -> None:
    headers = _admin(db)
    survey = _ready(client, db, headers, starts_at="2030-01-01T00:00:00Z")
    client.post(f"{URL}/{survey.id}/publish", headers=headers)
    queued.clear()

    made = client.post(f"{URL}/{survey.id}/duplicate", json={}, headers=headers)

    assert made.status_code == 200, made.text
    copy = client.get(f"{URL}/{made.json()['id']}", headers=headers).json()
    assert copy["name"] == "Oktabr (nusxa)" and copy["active"] is False
    assert copy["state"] == "ready" and copy["starts_at"] is None
    assert all(tab["filled"] for tab in copy["tabs"])
    assert [q["text"] for q in copy["questions"]] == ["S1 uz", "S2 uz", "S3 uz"]
    assert copy["questions"][2]["show_if"] == 1
    assert not queued


def test_a_copy_asks_everyone_unless_told_to_keep_who_was_asked(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    _, plan = _shop(db)
    person = _customer(db, plan, "a@client.test")
    survey = _ready(client, db, headers, people=[str(person.id)])
    assert survey.audience != "everyone"

    fresh = client.post(
        f"{URL}/{survey.id}/duplicate", json={"name": "Boshqalarga"}, headers=headers
    ).json()
    same = client.post(
        f"{URL}/{survey.id}/duplicate", json={"keep_audience": True}, headers=headers
    ).json()

    copy = client.get(f"{URL}/{fresh['id']}", headers=headers).json()
    assert copy["name"] == "Boshqalarga" and copy["people"] == []
    assert copy["plans"] == []
    kept = client.get(f"{URL}/{same['id']}", headers=headers).json()
    assert kept["name"].endswith("(nusxa)")
    assert kept["people"] == [str(person.id)] or kept["plans"] == [str(plan.id)]


def test_a_language_is_corrected_and_filling_the_last_makes_a_failed_one_ready(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    survey = _ready(client, db, headers)
    survey.state = SurveyState.FAILED
    survey.title = {"uz": survey.title["uz"], "ru": "R"}
    db.commit()

    page = client.get(f"{URL}/{survey.id}/languages/en", headers=headers).json()
    assert page["wording"]["title"] == "" and page["source"]["title"] == "Sarlavha uz"
    wording = {
        "title": "Title",
        "intro": "Intro",
        "questions": [
            {"text": q["text"], "options": q["options"]}
            for q in page["wording"]["questions"]
        ],
    }
    saved = client.put(f"{URL}/{survey.id}/languages/en", headers=headers, json=wording)

    assert saved.status_code == 200, saved.text
    assert client.get(f"{URL}/{survey.id}", headers=headers).json()["state"] == "ready"
    assert (
        client.get(f"{URL}/{survey.id}/languages/uz", headers=headers).status_code
        == 404
    )


def test_a_wording_of_another_shape_is_refused(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    survey = _ready(client, db, headers)
    short = {"title": "T", "intro": "", "questions": [{"text": "x", "options": []}]}
    refused = client.put(f"{URL}/{survey.id}/languages/ru", headers=headers, json=short)
    assert (
        refused.status_code == 400 and refused.json()["code"] == "translation_refused"
    )
    source = client.put(f"{URL}/{survey.id}/languages/uz", headers=headers, json=short)
    assert source.status_code == 400


def _language(code: str) -> SurveyLanguage:
    return SurveyLanguage(
        language=code,
        title=f"T {code}",
        intro=f"I {code}",
        questions=[
            TranslatedQuestion(text="a", options=[f"x {code}", f"y {code}"]),
            TranslatedQuestion(text="b"),
            TranslatedQuestion(text="c"),
        ],
    )


class _Result:
    def __init__(self, value: Any) -> None:
        self.value = value


def test_a_translation_is_written_when_it_is_the_same_survey(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    survey_id = _created(client, headers)
    member = db.scalar(select(User).where(User.is_staff.is_(True)))
    answer = _Result(SurveyTranslation(languages=[_language("ru"), _language("en")]))

    with (
        patch("app.modules.surveys.services.translate._ask", return_value=answer),
        patch("app.modules.audit.services.record_llm_result"),
    ):
        word = translate_survey(db, survey_id=survey_id, actor_id=str(member.id))

    assert word == "ready"
    one = client.get(f"{URL}/{survey_id}", headers=headers).json()
    assert one["state"] == "ready" and all(tab["filled"] for tab in one["tabs"])


def test_a_translation_of_another_shape_fails_whole(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    survey_id = _created(client, headers)
    member = db.scalar(select(User).where(User.is_staff.is_(True)))
    answer = _Result(SurveyTranslation(languages=[_language("ru")]))

    with (
        patch("app.modules.surveys.services.translate._ask", return_value=answer),
        patch("app.modules.audit.services.record_llm_result"),
    ):
        word = translate_survey(db, survey_id=survey_id, actor_id=str(member.id))

    assert word == "failed"
    one = client.get(f"{URL}/{survey_id}", headers=headers).json()
    assert one["state"] == "failed" and one["tabs"][1]["filled"] is False


def test_no_claude_marks_it_not_translated(client: TestClient, db: Session) -> None:
    from app.common.exceptions import LLMUnavailable

    headers = _admin(db)
    survey_id = _created(client, headers)
    member = db.scalar(select(User).where(User.is_staff.is_(True)))
    with patch(
        "app.modules.surveys.services.translate._ask", side_effect=LLMUnavailable("x")
    ):
        assert (
            translate_survey(db, survey_id=survey_id, actor_id=str(member.id))
            == "failed"
        )


def test_a_translation_saved_over_meanwhile_is_dropped(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    survey_id = _created(client, headers)
    member = db.scalar(select(User).where(User.is_staff.is_(True)))
    answer = _Result(SurveyTranslation(languages=[_language("ru"), _language("en")]))

    def saved_meanwhile(*_: Any) -> _Result:
        with db.get_bind().begin() as conn:
            conn.exec_driver_sql(
                "UPDATE surveys SET updated_at = now() + interval '1 second'"
            )
        return answer

    with (
        patch(
            "app.modules.surveys.services.translate._ask", side_effect=saved_meanwhile
        ),
        patch("app.modules.audit.services.record_llm_result"),
    ):
        word = translate_survey(db, survey_id=survey_id, actor_id=str(member.id))

    assert word == "stale"


def test_retranslating_a_failed_survey_queues_it_again(
    client: TestClient, db: Session, queued: list[Any]
) -> None:
    headers = _admin(db)
    survey = _ready(client, db, headers)
    survey.state = SurveyState.FAILED
    db.commit()
    queued.clear()
    done = client.post(f"{URL}/{survey.id}/retranslate", headers=headers)
    assert done.status_code == 200, done.text
    assert queued


def _due(client: TestClient, headers: dict[str, str]) -> Any:
    return client.get("/api/v1/surveys/due", headers=headers).json()["survey"]


def test_the_dates_and_the_wait_decide_who_is_asked(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    shop, plan = _shop(db)
    person = _customer(db, plan, "a@client.test", days=10)
    asked = _bearer(person)
    survey = _ready(client, db, headers)
    client.post(f"{URL}/{survey.id}/publish", headers=headers)
    assert _due(client, asked) is not None
    cache.delete(SNOOZE_KEY.format(user_id=person.id))

    survey.ask_after_days = 11
    db.commit()
    assert _due(client, asked) is None
    survey.ask_after_days = 0
    survey.starts_at = utcnow() + timedelta(days=1)
    db.commit()
    assert _due(client, asked) is None
    row = client.get(URL, headers=headers).json()[0]
    assert row["phase"] == "scheduled"

    survey.starts_at = utcnow() - timedelta(days=2)
    survey.ends_at = utcnow() - timedelta(days=1)
    db.commit()
    assert _due(client, asked) is None
    assert client.get(URL, headers=headers).json()[0]["phase"] == "ended"
    survey.ends_at = utcnow() + timedelta(days=1)
    db.commit()
    assert _due(client, asked) is not None
    assert shop.id is not None


def test_a_past_end_date_refuses_publishing(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    survey = _ready(client, db, headers, ends_at="2020-01-01T00:00:00Z")
    refused = client.post(f"{URL}/{survey.id}/publish", headers=headers)
    assert refused.status_code == 400 and refused.json()["code"] == "survey_ended"


def test_seeing_and_putting_off_are_counted_once_each(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    _, plan = _shop(db)
    person = _customer(db, plan, "a@client.test")
    asked = _bearer(person)
    survey = _ready(client, db, headers)
    client.post(f"{URL}/{survey.id}/publish", headers=headers)

    _due(client, asked)
    _due(client, asked)
    assert db.scalar(select(func.count(SurveySighting.id))) == 1
    client.post("/api/v1/surveys/later", headers=asked)
    cache.delete(SNOOZE_KEY.format(user_id=person.id))
    client.post("/api/v1/surveys/later", headers=asked)
    cache.delete(SNOOZE_KEY.format(user_id=person.id))

    funnel = client.get(f"{URL}/{survey.id}/results", headers=headers).json()["funnel"]
    assert funnel["seen"] == 1 and funnel["later"] == 1
    db.expire_all()
    assert db.scalar(select(SurveySighting.later_count)) == 2


def test_results_count_each_question(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    _, plan = _shop(db)
    a = _customer(db, plan, "a@client.test")
    b = _customer(db, plan, "b@client.test")
    _customer(db, plan, "c@client.test")
    survey = _ready(client, db, headers)
    _answer(db, survey, a, q1={"choices": [1]}, q2={"number": 2}, q3={"text": "Qimmat"},
            channel="bot")  # fmt: skip
    _answer(db, survey, b, q1={"choices": [0]}, q2={"number": 9})

    found = client.get(f"{URL}/{survey.id}/results", headers=headers).json()

    funnel = found["funnel"]
    assert funnel["answered"] == 2 and funnel["meant"] == 4, "the shop and three more"
    assert funnel["rate_percent"] == 50.0 and funnel["seen"] == 2
    choice, number, text = found["questions"]
    assert [o["count"] for o in choice["options"]] == [1, 1]
    assert choice["options"][0]["percent"] == 50.0 and choice["answered"] == 2
    assert number["average"] == 5.5
    assert [n["value"] for n in number["numbers"]][:2] == [0, 1]
    assert number["numbers"][2]["count"] == 1 and number["numbers"][2]["low"] is True
    assert number["numbers"][9]["low"] is False
    assert text["asked"] == 1 and text["answered"] == 1
    assert text["texts"][0]["text"] == "Qimmat"
    assert found["channels"] == {"bot": 1, "web": 1}
    assert sum(day["count"] for day in found["days"]) == 2
    assert found["low_total"] == 1
    assert found["low_scores"][0]["number"] == 2
    assert found["low_scores"][0]["customer_id"] == str(a.id)


def test_results_of_a_survey_with_no_answers_read_empty(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    survey = _ready(client, db, headers)
    found = client.get(f"{URL}/{survey.id}/results", headers=headers).json()
    assert found["funnel"]["rate_percent"] == 0.0
    assert found["questions"][1]["average"] is None
    assert found["low_scores"] == []


def test_answers_filter_by_every_field(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    _, plan = _shop(db)
    other = Plan(code="start", name="Start", price=1, currency="UZS", period_days=30,
                 max_adsets=1, llm_cost_limit_minor=0)  # fmt: skip
    db.add(other)
    db.flush()
    a = _customer(db, plan, "a@client.test")
    b = _customer(db, other, "b@client.test")
    survey = _ready(client, db, headers)
    long_ago = utcnow() - timedelta(days=40)
    first = _answer(db, survey, a, q3={"text": "Salom"}, channel="bot", language="ru",
                    at=long_ago)  # fmt: skip
    second = _answer(db, survey, b, q2={"number": 3})

    def ids(**params: str) -> list[str]:
        page = client.get(f"{URL}/responses", headers=headers, params=params)
        assert page.status_code == 200, page.text
        return [row["id"] for row in page.json()["rows"]]

    assert ids() == [str(second.id), str(first.id)]
    assert ids(survey=str(survey.id), channel="bot") == [str(first.id)]
    assert ids(language="ru") == [str(first.id)]
    assert ids(plan=str(other.id)) == [str(second.id)]
    assert ids(since=str((utcnow() - timedelta(days=2)).date())) == [str(second.id)]
    assert ids(until=str((utcnow() - timedelta(days=30)).date())) == [str(first.id)]

    db.add(
        SupportConversation(
            owner_id=b.id, last_office_at=utcnow() + timedelta(minutes=1)
        )
    )
    db.commit()
    assert ids(unreplied="true") == [str(first.id)]
    row = client.get(f"{URL}/responses", headers=headers).json()["rows"][0]
    assert row["replied"] is True
    assert (
        client.get(f"{URL}/responses?channel=fax", headers=headers).status_code == 422
    )

    one = client.get(f"{URL}/responses/{first.id}", headers=headers).json()
    assert one["gist"] == "Salom"
    assert one["lines"] == [{"question": "S3 uz", "kind": "text", "answer": "Salom"}]
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"{URL}/responses/{missing}", headers=headers).status_code == 404


def test_the_excel_holds_a_customer_per_row(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    _, plan = _shop(db)
    person = _customer(db, plan, "a@client.test")
    survey = _ready(client, db, headers)
    _answer(db, survey, person, q1={"choices": [0]}, q2={"number": 9})

    sheet = client.get(f"{URL}/{survey.id}/excel", headers=headers)

    assert sheet.status_code == 200
    assert sheet.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'filename="sorovnoma-' in sheet.headers["content-disposition"]
    assert sheet.content[:2] == b"PK"


def test_a_ticked_plan_is_kept_whole_and_the_rest_by_name(
    client: TestClient, db: Session
) -> None:
    headers = _admin(db)
    shop, plan = _shop(db)
    other = Plan(code="start", name="Start", price=1, currency="UZS", period_days=30,
                 max_adsets=1, llm_cost_limit_minor=0)  # fmt: skip
    db.add(other)
    db.flush()
    a = _customer(db, plan, "a@client.test")
    b = _customer(db, other, "b@client.test")
    _customer(db, other, "c@client.test")

    roster = client.get(f"{URL}/roster", headers=headers).json()
    assert {line["name"]: line["total"] for line in roster["plans"]} == {
        "Pro": 2,
        "Start": 2,
    }

    survey_id = _created(client, headers, people=[str(shop.id), str(a.id), str(b.id)])
    one = client.get(f"{URL}/{survey_id}", headers=headers).json()
    assert one["plans"] == [str(plan.id)] and one["people"] == [str(b.id)]
    row = client.get(URL, headers=headers).json()[0]
    assert row["audience"] == "people" and row["plans"] == ["Pro"]


def test_ticking_everyone_is_everyone(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    shop, _ = _shop(db)
    survey_id = _created(client, headers, people=[str(shop.id)])
    assert client.get(URL, headers=headers).json()[0]["audience"] == "everyone"
    assert client.get(f"{URL}/{survey_id}", headers=headers).json()["people"] == []


def test_a_customers_card_lists_their_answers(client: TestClient, db: Session) -> None:
    headers = _admin(db)
    _, plan = _shop(db)
    person = _customer(db, plan, "a@client.test")
    survey = _ready(client, db, headers)
    _answer(db, survey, person, q3={"text": "Zo'r"})
    base = "/api/v1/office/customers"

    rows = client.get(f"{base}/{person.id}/surveys", headers=headers).json()["rows"]

    assert rows[0]["survey"] == "Oktabr" and rows[0]["gist"] == "Zo'r"
    _, seller = _staff(db, Role.SALES, email="seller@office.test")
    assert client.get(f"{base}/{person.id}/surveys", headers=seller).status_code == 404


def test_a_customer_deleted_takes_their_sightings(
    client: TestClient, db: Session
) -> None:
    headers = _staff(db, Role.OWNER, email="owner@office.test")[1]
    shop, _ = _shop(db)
    survey = _ready(client, db, headers)
    db.add(SurveySighting(survey_id=survey.id, owner_id=shop.id))
    db.commit()

    gone = client.post(
        f"/api/v1/office/customers/{shop.id}/delete",
        headers=headers,
        json={"email": shop.email},
    )

    assert gone.status_code == 200, gone.text
    assert db.scalar(select(func.count(SurveySighting.id))) == 0
