from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.models import Event
from app.modules.billing.models import Plan
from app.modules.billing.services import start_trial
from app.modules.surveys.constants import SNOOZE_KEY
from app.modules.surveys.models import (
    Survey,
    SurveyQuestion,
    SurveyResponse,
    surveys_people,
    surveys_plans,
)
from tests.pg.conftest import sign_up

DUE = "/api/v1/surveys/due"
ANSWER = "/api/v1/surveys/answer"
LATER = "/api/v1/surveys/later"


def _customer(client: TestClient, db: Session) -> tuple[dict[str, str], User]:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    start_trial(db, user=user, now=utcnow())
    db.commit()
    return auth, user


def _survey(db: Session, *, audience: str = "everyone", ago: int = 1) -> Survey:
    """Did it help? - why not (only after "no") - a mark from 0 to 10."""
    survey = Survey(
        name="Oylik",
        audience=audience,
        source_language="uz",
        title={"uz": "Fikringiz", "ru": "Ваше мнение"},
        intro={"uz": "Ikki savol", "ru": "Два вопроса"},
        state="ready",
        is_active=True,
        published_at=utcnow() - timedelta(days=ago),
    )
    db.add(survey)
    db.flush()
    db.add_all(
        [
            SurveyQuestion(
                survey_id=survey.id,
                position=1,
                kind="choice",
                text={"uz": "Yordam berdimi?", "ru": "Помогло?"},
                options=[{"uz": "Ha", "ru": "Да"}, {"uz": "Yo'q", "ru": "Нет"}],
            ),
            SurveyQuestion(
                survey_id=survey.id,
                position=2,
                kind="text",
                text={"uz": "Nega?", "ru": "Почему?"},
                show_if=1,
                show_options=[1],
            ),
            SurveyQuestion(
                survey_id=survey.id,
                position=3,
                kind="number",
                text={"uz": "Baho", "ru": "Оценка"},
                min_value=0,
                max_value=10,
            ),
        ]
    )
    db.commit()
    return survey


def _ids(db: Session, survey: Survey) -> list[str]:
    return [
        str(pk)
        for pk in db.scalars(
            select(SurveyQuestion.id)
            .where(SurveyQuestion.survey_id == survey.id)
            .order_by(SurveyQuestion.position)
        )
    ]


def test_nothing_is_due_without_a_live_plan(client: TestClient, db: Session) -> None:
    auth = sign_up(client)
    _survey(db)
    due = client.get(DUE, headers=auth)
    assert due.status_code == 200, due.text
    assert due.json() == {"survey": None, "always": 0}


def test_due_in_the_readers_language(client: TestClient, db: Session) -> None:
    auth, _ = _customer(client, db)
    survey = _survey(db)
    client.put("/api/v1/account/language", json={"language": "ru"}, headers=auth)

    body = client.get(DUE, headers=auth).json()
    asked = body["survey"]
    assert asked["survey_id"] == str(survey.id)
    assert asked["language"] == "ru"
    assert asked["title"] == "Ваше мнение"
    assert [q["text"] for q in asked["questions"]] == ["Помогло?", "Почему?", "Оценка"]
    assert asked["questions"][0]["options"] == ["Да", "Нет"]
    assert asked["questions"][1]["show_if"] == 1
    assert asked["questions"][1]["show_options"] == [1]
    assert asked["questions"][2]["numbers"] == list(range(11))
    # The hung question is not counted until "no" is picked.
    assert body["always"] == 2

    client.put("/api/v1/account/language", json={"language": "en"}, headers=auth)
    fallback = client.get(DUE, headers=auth).json()["survey"]
    assert fallback["language"] == "uz" and fallback["title"] == "Fikringiz"


def test_the_first_published_is_asked_first(client: TestClient, db: Session) -> None:
    auth, _ = _customer(client, db)
    later = _survey(db, ago=1)
    first = _survey(db, ago=5)
    assert client.get(DUE, headers=auth).json()["survey"]["survey_id"] == str(first.id)
    assert later.id != first.id


def test_audience_by_plan_and_by_person(client: TestClient, db: Session) -> None:
    auth, user = _customer(client, db)
    other = Plan(
        code="other",
        name="Other",
        tagline="",
        features="",
        price=1,
        currency="USD",
        period_days=30,
        max_adsets=1,
        daily_chat_requests=1,
        llm_cost_limit_minor=1,
        included_pages=1,
        included_google_accounts=0,
        extra_page_price=0,
        is_one_time=False,
        is_active=True,
        sort_order=2,
    )
    db.add(other)
    survey = _survey(db, audience="plans")
    db.execute(insert(surveys_plans).values(survey_id=survey.id, plan_id=other.id))
    db.commit()
    assert client.get(DUE, headers=auth).json()["survey"] is None

    db.execute(insert(surveys_people).values(survey_id=survey.id, user_id=user.id))
    db.commit()
    assert client.get(DUE, headers=auth).json()["survey"]["survey_id"] == str(survey.id)


def test_staff_are_never_asked(client: TestClient, db: Session) -> None:
    auth, user = _customer(client, db)
    _survey(db)
    user.is_staff = True
    db.commit()
    assert client.get(DUE, headers=auth).json()["survey"] is None


def test_answer_checks_only_the_questions_asked(
    client: TestClient, db: Session
) -> None:
    auth, user = _customer(client, db)
    survey = _survey(db)
    choice, why, mark = _ids(db, survey)

    refused = client.post(
        ANSWER,
        json={"survey": str(survey.id), "answers": {choice: ["1"], mark: ["11"]}},
        headers=auth,
    )
    assert refused.status_code == 400
    assert refused.json() == {
        "detail": "Javoblarni tekshiring.",
        "code": "survey_answer_invalid",
        "problems": {why: "Javob bering.", mark: "Raqamni tanlang."},
    }

    both = client.post(
        ANSWER,
        json={"survey": str(survey.id), "answers": {choice: ["0", "1"]}},
        headers=auth,
    )
    assert both.json()["problems"][choice] == "Faqat bitta variant tanlang."

    kept = client.post(
        ANSWER,
        json={
            "survey": str(survey.id),
            # "Yes" was picked, so the hung question is dropped.
            "answers": {choice: ["0"], why: ["ignored"], mark: [" 9 "]},
            "channel": "miniapp",
        },
        headers=auth,
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["title"] == "Rahmat!"

    response = db.scalar(select(SurveyResponse))
    assert response is not None
    assert response.owner_id == user.id
    assert response.channel == "miniapp"
    assert response.language == "uz"
    assert response.answers == [
        {"question": choice, "kind": "choice", "choices": [0]},
        {"question": mark, "kind": "number", "number": 9},
    ]
    event = db.scalar(select(Event).where(Event.name == "survey.answered"))
    assert event is not None
    assert event.payload == {"response_id": str(response.id)}

    assert client.get(DUE, headers=auth).json()["survey"] is None
    again = client.post(
        ANSWER,
        json={"survey": str(survey.id), "answers": {choice: ["0"], mark: ["1"]}},
        headers=auth,
    )
    assert again.status_code == 400
    assert again.json()["code"] == "survey_not_due"


def test_closed_or_unknown_survey_is_not_due(client: TestClient, db: Session) -> None:
    auth, _ = _customer(client, db)
    survey = _survey(db)
    junk = client.post(ANSWER, json={"survey": "nope", "answers": {}}, headers=auth)
    assert junk.status_code == 400
    assert junk.json() == {
        "detail": "Bu so'rovnoma endi yopilgan. Sahifani yangilang.",
        "code": "survey_not_due",
    }
    survey.is_active = False
    db.commit()
    closed = client.post(
        ANSWER, json={"survey": str(survey.id), "answers": {}}, headers=auth
    )
    assert closed.json()["code"] == "survey_not_due"


def test_later_holds_it_back_and_an_answer_clears_the_wait(
    client: TestClient, db: Session
) -> None:
    auth, user = _customer(client, db)
    survey = _survey(db)
    choice, _, mark = _ids(db, survey)

    later = client.post(LATER, headers=auth)
    assert later.status_code == 200
    assert later.json() == {"ask_again_in": 605}
    assert client.get(DUE, headers=auth).json()["survey"] is None

    # A dialog left open still sends; an invalid one while snoozed is closed.
    invalid = client.post(
        ANSWER, json={"survey": str(survey.id), "answers": {}}, headers=auth
    )
    assert invalid.json()["code"] == "survey_not_due"

    kept = client.post(
        ANSWER,
        json={"survey": str(survey.id), "answers": {choice: ["0"], mark: ["3"]}},
        headers=auth,
    )
    assert kept.status_code == 200, kept.text
    assert cache.get(SNOOZE_KEY.format(user_id=user.id)) is None
