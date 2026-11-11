"""A customer's answers to the survey they were asked.

The same door for the cabinet, the mini app and the bot: each hands
``{question id: [values]}`` here, merged over what was already kept.

``save_progress`` keeps every answer given so far, as it is given, with
nothing required: a reader who leaves halfway leaves their answers behind,
and is asked again from there. ``answer_survey`` finishes it: every asked
question is checked against its kind and nothing is written unless all pass.
A question hung on an earlier choice that was not picked is dropped, required
or not. Whether the survey is still owed is checked again rather than taken
from the page.

Each kept answer also carries the question and the answer as the office read
them then (``q``, ``a``), so an answer stays readable after the survey is
edited.
"""

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.surveys.constants import (
    ANSWER_TEXT_MAX,
    SNOOZE_KEY,
    QuestionKind,
    ResponseChannel,
)
from app.modules.surveys.exceptions import SurveyAnswerInvalid, SurveyNotDue
from app.modules.surveys.models import Survey, SurveyQuestion, SurveyResponse
from app.modules.surveys.selectors import owed_for, raw_of
from app.modules.surveys.selectors.office import office_language, shown
from core.surveys import Rule, asked_positions

logger = logging.getLogger(__name__)
ALREADY = "Bu so'rovnomaga javobingiz allaqachon bor."


def answer_survey(
    db: Session,
    *,
    owner: User,
    survey_id: uuid.UUID | str,
    raw: Mapping[str, Sequence[str]],
    language: str,
    channel: ResponseChannel,
) -> SurveyResponse:
    """Check every answer and finish it, once per customer. Caller commits."""
    survey = _owed(db, owner=owner, survey_id=survey_id)
    response = _response(db, owner=owner, survey=survey)
    questions = _questions(db, survey)
    merged = _merged(response, raw)
    answers, problems = _cleaned(
        questions=_asked(questions, merged), raw=merged, lang=office_language(survey)
    )
    if problems:
        raise SurveyAnswerInvalid(problems)
    try:
        with db.begin_nested():
            response = _write(
                db,
                owner=owner,
                survey=survey,
                response=response,
                answers=answers,
                language=language,
                channel=channel,
                finished=True,
            )
            emit(
                db,
                owner_id=owner.id,
                name=EventName.SURVEY_ANSWERED,
                aggregate_type="survey",
                aggregate_id=survey.id,
                payload={"response_id": str(response.id)},
            )
    except IntegrityError:
        raise SurveyNotDue(ALREADY) from None
    cache.delete(SNOOZE_KEY.format(user_id=owner.id))
    logger.info("survey %s answered by %s", survey.id, owner.id)
    return response


def save_progress(
    db: Session,
    *,
    owner: User,
    survey_id: uuid.UUID | str,
    raw: Mapping[str, Sequence[str]],
    language: str,
    channel: ResponseChannel,
) -> SurveyResponse | None:
    """Keep what is answered so far; nothing is required and an answer that
    does not fit its question is left out rather than refused. ``None`` while
    nothing at all is answered. Caller commits."""
    survey = _owed(db, owner=owner, survey_id=survey_id)
    response = _response(db, owner=owner, survey=survey)
    questions = _questions(db, survey)
    merged = _merged(response, raw)
    answers, problems = _cleaned(
        questions=_asked(questions, merged), raw=merged, lang=office_language(survey)
    )
    kept = [
        item for item in answers if item["question"] not in problems and _given(item)
    ]
    if not kept and response is None:
        return None
    try:
        with db.begin_nested():
            return _write(
                db,
                owner=owner,
                survey=survey,
                response=response,
                answers=kept,
                language=language,
                channel=channel,
                finished=False,
            )
    except IntegrityError:
        # Saved from another screen at the same moment: that save stands.
        return None


def _owed(db: Session, *, owner: User, survey_id: uuid.UUID | str) -> Survey:
    found = owed_for(db, user=owner)
    survey: Survey | None = (
        db.scalars(found.where(Survey.id == _uuid(survey_id)).limit(1)).first()
        if found is not None
        else None
    )
    if survey is None:
        raise SurveyNotDue
    return survey


def _response(db: Session, *, owner: User, survey: Survey) -> SurveyResponse | None:
    """This reader's unfinished answer, locked; a finished one is refused."""
    response = db.scalar(
        select(SurveyResponse)
        .where(
            SurveyResponse.owner_id == owner.id, SurveyResponse.survey_id == survey.id
        )
        .with_for_update()
    )
    if response is not None and response.completed_at is not None:
        raise SurveyNotDue(ALREADY)
    return response


def _questions(db: Session, survey: Survey) -> list[SurveyQuestion]:
    return list(
        db.scalars(
            select(SurveyQuestion)
            .where(SurveyQuestion.survey_id == survey.id)
            .order_by(SurveyQuestion.position)
        )
    )


def _merged(
    response: SurveyResponse | None, raw: Mapping[str, Sequence[str]]
) -> dict[str, list[str]]:
    """What was kept before, with what came now over it."""
    merged = raw_of(response.answers) if response is not None else {}
    merged.update({str(key): [str(v) for v in values] for key, values in raw.items()})
    return merged


def _write(
    db: Session,
    *,
    owner: User,
    survey: Survey,
    response: SurveyResponse | None,
    answers: list[dict[str, Any]],
    language: str,
    channel: ResponseChannel,
    finished: bool,
) -> SurveyResponse:
    now = utcnow()
    if response is None:
        response = SurveyResponse(owner_id=owner.id, survey_id=survey.id)
        db.add(response)
    response.answers = answers
    response.language = language
    response.channel = str(channel)
    response.updated_at = now
    if finished:
        response.completed_at = now
    db.flush()
    return response


def _given(item: Mapping[str, Any]) -> bool:
    return any(key in item for key in ("text", "choices", "number"))


def _uuid(value: uuid.UUID | str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        raise SurveyNotDue from None


def _asked(
    questions: list[SurveyQuestion], raw: Mapping[str, Sequence[str]]
) -> list[SurveyQuestion]:
    """The questions these answers lead through, in order."""
    picks = {
        row.position: {
            int(value) for value in raw.get(str(row.id), ()) if str(value).isdigit()
        }
        for row in questions
        if row.kind == QuestionKind.CHOICE and not _single_wrong(row, raw)
    }
    rules = [
        Rule(row.position, row.show_if or 0, tuple(row.show_options or ()))
        for row in questions
    ]
    shown = set(asked_positions(rules, picks))
    return [row for row in questions if row.position in shown]


def _single_wrong(row: SurveyQuestion, raw: Mapping[str, Sequence[str]]) -> bool:
    """Several picks on a one-pick question open nothing; it is refused."""
    return not row.allows_many and len(raw.get(str(row.id), ())) > 1


def _cleaned(
    *, questions: list[SurveyQuestion], raw: Mapping[str, Sequence[str]], lang: str
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    answers: list[dict[str, Any]] = []
    problems: dict[str, str] = {}
    for row in questions:
        values = [str(value).strip() for value in raw.get(str(row.id), [])]
        values = [value for value in values if value]
        value, problem = _one(row, values)
        if problem:
            problems[str(row.id)] = problem
        item: dict[str, Any] = {"question": str(row.id), "kind": row.kind, **value}
        item["q"] = row.text.get(lang, "")
        item["a"] = shown(row, item, lang) if value else ""
        answers.append(item)
    return answers, problems


def _one(row: SurveyQuestion, values: list[str]) -> tuple[dict[str, Any], str]:
    if not values:
        return {}, ("Javob bering." if row.is_required else "")
    if row.kind == QuestionKind.TEXT:
        text = values[0]
        if len(text) > ANSWER_TEXT_MAX:
            return {}, f"Javob {ANSWER_TEXT_MAX} belgidan oshmasin."
        return {"text": text}, ""
    if row.kind == QuestionKind.CHOICE:
        return _choices(row, values)
    return _number(row, values[0])


def _choices(row: SurveyQuestion, values: list[str]) -> tuple[dict[str, Any], str]:
    try:
        picks = sorted({int(value) for value in values})
    except ValueError:
        return {}, "Variantlardan tanlang."
    if any(pick < 0 or pick >= len(row.options) for pick in picks):
        return {}, "Variantlardan tanlang."
    if len(picks) > 1 and not row.allows_many:
        return {}, "Faqat bitta variant tanlang."
    return {"choices": picks}, ""


def _number(row: SurveyQuestion, value: str) -> tuple[dict[str, Any], str]:
    try:
        number = int(value)
    except ValueError:
        return {}, "Raqamni tanlang."
    low, high = row.min_value, row.max_value
    if low is None or high is None or not low <= number <= high:
        return {}, "Raqamni tanlang."
    return {"number": number}, ""
