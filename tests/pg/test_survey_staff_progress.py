"""Staff trying a survey on themselves, answers kept as they are given, and
who an edited survey still asks."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.modules.backoffice.constants import Role
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.services import handle_update
from app.modules.notifications.services.announce_survey import (
    deliver_survey_for,
    survey_audience,
)
from app.modules.notifications.services.survey_bot import start_survey
from app.modules.notifications.services.survey_state import clear
from app.modules.surveys.models import Survey, SurveyResponse, surveys_people
from app.modules.surveys.selectors import due_survey
from tests.pg.test_bot_surveys import NOON, _button, _linked, _sent, phone  # noqa: F401
from tests.pg.test_office_actions import _shop, _staff
from tests.pg.test_office_surveys import URL
from tests.pg.test_office_surveys import _customer as _office_customer
from tests.pg.test_office_telegram import FakeBot, _press
from tests.pg.test_surveys import _customer, _ids, _survey

DUE = "/api/v1/surveys/due"
ANSWER = "/api/v1/surveys/answer"
PROGRESS = "/api/v1/surveys/progress"


def _pick(db: Session, survey: Survey, *people: Any) -> None:
    db.execute(
        insert(surveys_people),
        [{"survey_id": survey.id, "user_id": person.id} for person in people],
    )
    db.commit()


# --- staff ---------------------------------------------------------------


def test_the_roster_lists_staff_and_a_ticked_one_is_kept_by_name(
    client: TestClient, db: Session
) -> None:
    member, headers = _staff(db, Role.SUPPORT, email="support@office.test")
    shop, plan = _shop(db)
    customer = _office_customer(db, plan, "a@client.test")

    persons = client.get(f"{URL}/roster", headers=headers).json()["persons"]
    by_id = {person["id"]: person for person in persons}
    assert by_id[str(member.id)]["staff"] is True
    assert by_id[str(member.id)]["plan_id"] == ""
    assert by_id[str(customer.id)]["staff"] is False

    # Every customer and a staff member ticked: not "everyone", which never
    # asks staff.
    body = {
        "name": "Sinov",
        "source_language": "uz",
        "title": "Sinov",
        "questions": [{"kind": "text", "text": "Qalay?"}],
        "people": [str(shop.id), str(customer.id), str(member.id)],
    }
    made = client.post(URL, headers=headers, json=body)
    assert made.status_code == 200, made.text
    detail = client.get(f"{URL}/{made.json()['id']}", headers=headers).json()
    assert str(member.id) in detail["people"]
    assert detail["plans"] == [str(plan.id)]


def test_staff_are_asked_only_what_picked_them_with_no_plan_or_wait(
    client: TestClient, db: Session
) -> None:
    member, headers = _staff(db, Role.SUPPORT, email="support@office.test")
    everyone = _survey(db)
    assert client.get(DUE, headers=headers).json()["survey"] is None

    picked = _survey(db, audience="people", ago=0)
    picked.ask_after_days = 30
    db.commit()
    _pick(db, picked, member)

    due = client.get(DUE, headers=headers).json()["survey"]
    assert due is not None and due["survey_id"] == str(picked.id)
    assert due["survey_id"] != str(everyone.id)
    choice, _why, mark = _ids(db, picked)
    done = client.post(
        ANSWER,
        headers=headers,
        json={"survey": str(picked.id), "answers": {choice: ["0"], mark: ["7"]}},
    )
    assert done.status_code == 200, done.text
    assert client.get(DUE, headers=headers).json()["survey"] is None


def test_a_picked_staff_member_gets_it_in_the_bot(
    client: TestClient,
    db: Session,
    phone: FakeBot,  # noqa: F811
) -> None:
    member, _ = _staff(db, Role.SUPPORT, email="support@office.test")
    picked = _survey(db, audience="people")
    _pick(db, picked, member)
    _linked(db, member)

    assert str(member.id) in survey_audience(db, now=NOON)
    assert deliver_survey_for(db, owner=member, now=NOON) == "sent"
    # In the staff member's own language.
    assert "Помогло?" in _sent(phone)[-1]["text"]


# --- answers kept as given ----------------------------------------------


def test_each_answer_is_kept_and_the_dialog_opens_where_it_was_left(
    client: TestClient, db: Session
) -> None:
    auth, _user = _customer(client, db)
    survey = _survey(db)
    choice, why, mark = _ids(db, survey)

    nothing = client.post(
        PROGRESS, headers=auth, json={"survey": str(survey.id), "answers": {}}
    )
    assert nothing.json() == {"saved": 0}
    assert db.scalar(select(SurveyResponse)) is None

    first = client.post(
        PROGRESS,
        headers=auth,
        json={"survey": str(survey.id), "answers": {choice: ["1"], mark: ["99"]}},
    )
    # The number is out of its scale: left out, not refused.
    assert first.status_code == 200 and first.json() == {"saved": 1}
    client.post(
        PROGRESS,
        headers=auth,
        json={"survey": str(survey.id), "answers": {why: ["Qimmat"]}},
    )

    db.expire_all()
    kept = db.scalar(select(SurveyResponse))
    assert kept is not None and kept.completed_at is None
    assert {item["question"] for item in kept.answers} == {choice, why}

    due = client.get(DUE, headers=auth).json()["survey"]
    assert due["survey_id"] == str(survey.id)
    assert due["saved"] == {choice: ["1"], why: ["Qimmat"]}

    office = _staff(db, Role.SUPPORT, email="support@office.test")[1]
    row = next(
        r for r in client.get(URL, headers=office).json() if r["id"] == str(survey.id)
    )
    assert (row["answers"], row["partial"]) == (0, 1)
    listed = client.get(f"{URL}/responses?finished=false", headers=office).json()
    assert [r["finished"] for r in listed["rows"]] == [False]

    done = client.post(
        ANSWER, headers=auth, json={"survey": str(survey.id), "answers": {mark: ["8"]}}
    )
    assert done.status_code == 200, done.text
    db.expire_all()
    rows = list(db.scalars(select(SurveyResponse)))
    assert len(rows) == 1 and rows[0].id == kept.id and rows[0].completed_at
    assert {item["question"] for item in rows[0].answers} == {choice, why, mark}
    assert client.get(DUE, headers=auth).json()["survey"] is None
    late = client.post(
        PROGRESS, headers=auth, json={"survey": str(survey.id), "answers": {}}
    )
    assert late.status_code == 400 and late.json()["code"] == "survey_not_due"
    results = client.get(f"{URL}/{survey.id}/results", headers=office).json()
    assert (results["funnel"]["answered"], results["funnel"]["partial"]) == (1, 0)


def test_a_change_of_choice_drops_the_answer_it_hid(
    client: TestClient, db: Session
) -> None:
    auth, _ = _customer(client, db)
    survey = _survey(db)
    choice, why, _ = _ids(db, survey)
    client.post(
        PROGRESS,
        headers=auth,
        json={"survey": str(survey.id), "answers": {choice: ["1"], why: ["Qimmat"]}},
    )
    client.post(
        PROGRESS,
        headers=auth,
        json={"survey": str(survey.id), "answers": {choice: ["0"]}},
    )
    db.expire_all()
    kept = db.scalar(select(SurveyResponse))
    assert kept is not None
    assert [item["question"] for item in kept.answers] == [choice]


def test_the_bot_keeps_each_answer_and_picks_up_where_it_was_left(
    client: TestClient,
    db: Session,
    phone: FakeBot,  # noqa: F811
) -> None:
    _auth, user = _customer(client, db)
    survey = _survey(db)
    chat = _linked(db, user)
    choice, why, _ = _ids(db, survey)

    assert deliver_survey_for(db, owner=user, now=NOON) == "sent"
    no = _button(_sent(phone)[-1], "Yo'q")
    handle_update(db, payload=_press("700", no.data, message_id=101), now=NOON)

    db.expire_all()
    kept = db.scalar(select(SurveyResponse))
    assert kept is not None and kept.completed_at is None
    assert kept.channel == "bot"
    assert [item["question"] for item in kept.answers] == [choice]

    # The chat's state is lost (three days in the cache): the next start
    # opens from the kept answers, on the question after them.
    clear(db.get(TelegramChat, chat.id))
    due = due_survey(db, user=user, language="uz")
    assert due is not None and due.saved == {choice: ["1"]}
    start_survey(db, client=phone, chat=chat, due=due, now=NOON)
    assert "Nega?" in _sent(phone)[-1]["text"]
    assert why in {question.id for question in due.questions}


# --- an edited survey ----------------------------------------------------


def test_an_edited_survey_skips_who_finished_and_asks_who_was_added(
    client: TestClient, db: Session
) -> None:
    headers = _staff(db, Role.SUPPORT, email="support@office.test")[1]
    _, plan = _shop(db)
    first = _office_customer(db, plan, "a@client.test")
    second = _office_customer(db, plan, "b@client.test")
    survey = _survey(db, audience="people")
    _pick(db, survey, first)
    db.add(
        SurveyResponse(
            owner_id=first.id,
            survey_id=survey.id,
            language="uz",
            channel="web",
            answers=[],
            completed_at=survey.published_at,
        )
    )
    db.commit()

    detail = client.get(f"{URL}/{survey.id}", headers=headers).json()
    body = {
        "name": detail["name"],
        "source_language": "uz",
        "title": "Yangilangan",
        "intro": detail["intro"],
        "questions": [
            {
                **{k: q[k] for k in ("id", "kind", "text", "options", "is_required")},
                "min_value": q["min_value"],
                "max_value": q["max_value"],
                "show_if": q["show_if"],
                "show_options": q["show_options"],
            }
            for q in detail["questions"]
        ],
        "people": [str(first.id), str(second.id)],
        "ask_after_days": 0,
    }
    saved = client.put(f"{URL}/{survey.id}", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    db.expire_all()
    edited = db.get(Survey, survey.id)
    assert edited is not None
    edited.state = "ready"
    db.commit()

    assert due_survey(db, user=first, language="uz") is None
    asked = due_survey(db, user=second, language="uz")
    assert asked is not None and asked.title == "Yangilangan"
