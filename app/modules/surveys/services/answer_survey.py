"""A customer's answer to the survey they were asked.

The same door for the cabinet, the mini app and the bot: each hands
``{question id: [values]}`` here. Every asked question is checked against
its kind and nothing is written unless all pass. A question hung on an
earlier choice that was not picked is dropped, required or not. Whether
the survey is still owed is checked again rather than taken from the page.
"""

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.billing.selectors import live_subscription
from app.modules.surveys.constants import (
    ANSWER_TEXT_MAX,
    SNOOZE_KEY,
    QuestionKind,
    ResponseChannel,
)
from app.modules.surveys.exceptions import SurveyAnswerInvalid, SurveyNotDue
from app.modules.surveys.models import Survey, SurveyQuestion, SurveyResponse
from app.modules.surveys.selectors import owed
from core.surveys import Rule, asked_positions

logger = logging.getLogger(__name__)


def answer_survey(
    db: Session,
    *,
    owner: User,
    survey_id: uuid.UUID | str,
    raw: Mapping[str, Sequence[str]],
    language: str,
    channel: ResponseChannel,
) -> SurveyResponse:
    """Check every answer and keep them, once per customer. Caller commits."""
    subscription = live_subscription(db, owner=owner)
    survey: Survey | None = (
        db.scalars(
            owed(user=owner, plan_id=subscription.plan_id)
            .where(Survey.id == _uuid(survey_id))
            .limit(1)
        ).first()
        if subscription is not None
        else None
    )
    if survey is None:
        raise SurveyNotDue
    questions = list(
        db.scalars(
            select(SurveyQuestion)
            .where(SurveyQuestion.survey_id == survey.id)
            .order_by(SurveyQuestion.position)
        )
    )
    answers, problems = _cleaned(questions=_asked(questions, raw), raw=raw)
    if problems:
        raise SurveyAnswerInvalid(problems)
    response = SurveyResponse(
        owner_id=owner.id,
        survey_id=survey.id,
        language=language,
        channel=str(channel),
        answers=answers,
    )
    try:
        with db.begin_nested():
            db.add(response)
            db.flush()
            emit(
                db,
                owner_id=owner.id,
                name=EventName.SURVEY_ANSWERED,
                aggregate_type="survey",
                aggregate_id=survey.id,
                payload={"response_id": str(response.id)},
            )
    except IntegrityError:
        raise SurveyNotDue("Bu so'rovnomaga javobingiz allaqachon bor.") from None
    cache.delete(SNOOZE_KEY.format(user_id=owner.id))
    logger.info("survey %s answered by %s", survey.id, owner.id)
    return response


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
    *, questions: list[SurveyQuestion], raw: Mapping[str, Sequence[str]]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    answers: list[dict[str, Any]] = []
    problems: dict[str, str] = {}
    for row in questions:
        values = [str(value).strip() for value in raw.get(str(row.id), [])]
        values = [value for value in values if value]
        value, problem = _one(row, values)
        if problem:
            problems[str(row.id)] = problem
        answers.append({"question": str(row.id), "kind": row.kind, **value})
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
