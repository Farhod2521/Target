"""The survey a customer is owed right now, in their language, or none.

Owed to a customer on a live plan (a trial counts) it is meant for:
everyone, everyone on its plans, or the people the office picked. Asked
once; an answer anywhere closes it. The first published is asked first.
A customer who pressed "later" is left alone everywhere until it runs out.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.billing.selectors import live_subscription
from app.modules.surveys.constants import SNOOZE_KEY, QuestionKind, SurveyAudience
from app.modules.surveys.models import (
    Survey,
    SurveyQuestion,
    SurveyResponse,
    surveys_people,
    surveys_plans,
)
from core.surveys import Rule, asked_positions


@dataclass(frozen=True, slots=True)
class AskedQuestion:
    """One question as the customer reads it, and what it hangs on."""

    id: str
    position: int
    kind: str
    text: str
    options: tuple[str, ...]
    allows_many: bool
    numbers: tuple[int, ...]
    is_required: bool
    show_if: int = 0
    show_options: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DueSurvey:
    """The survey and its words in one language."""

    survey_id: str
    language: str
    title: str
    intro: str
    questions: tuple[AskedQuestion, ...]

    def asked(self, raw: Mapping[str, Sequence[str]]) -> list[int]:
        """Indexes of the questions asked, given ``{question id: [values]}``."""
        return asked_steps(self.questions, raw)


def asked_steps(
    questions: Sequence[AskedQuestion], raw: Mapping[str, Sequence[str]]
) -> list[int]:
    """Indexes into ``questions`` of those asked for these answers.

    A choice's values are option positions as strings; anything else opens
    nothing.
    """
    picks: dict[int, set[int]] = {}
    for question in questions:
        if question.kind != QuestionKind.CHOICE:
            continue
        picks[question.position] = {
            int(value) for value in raw.get(question.id, ()) if str(value).isdigit()
        }
    rules = [
        Rule(question.position, question.show_if, question.show_options)
        for question in questions
    ]
    shown = set(asked_positions(rules, picks))
    return [i for i, question in enumerate(questions) if question.position in shown]


def due_survey(db: Session, *, user: User, language: str) -> DueSurvey | None:
    """What to ask this customer now, or ``None``. Three queries at most."""
    if user.is_staff or cache.get(SNOOZE_KEY.format(user_id=user.id)):
        return None
    subscription = live_subscription(db, owner=user)
    if subscription is None:
        return None
    survey = db.scalars(owed(user=user, plan_id=subscription.plan_id).limit(1)).first()
    if survey is None:
        return None
    return _asked(db, survey=survey, language=language)


def owed(*, user: User, plan_id: uuid.UUID) -> Select[tuple[Survey]]:
    """The live surveys meant for this customer and not yet answered by
    them, the first published first. ``plan_id`` is their live plan's."""
    on_plan = exists().where(
        surveys_plans.c.survey_id == Survey.id, surveys_plans.c.plan_id == plan_id
    )
    picked = exists().where(
        surveys_people.c.survey_id == Survey.id, surveys_people.c.user_id == user.id
    )
    answered = exists().where(
        SurveyResponse.owner_id == user.id, SurveyResponse.survey_id == Survey.id
    )
    return (
        select(Survey)
        .where(
            Survey.is_active.is_(True),
            or_(
                Survey.audience == SurveyAudience.EVERYONE,
                and_(
                    Survey.audience != SurveyAudience.EVERYONE,
                    or_(on_plan, picked),
                ),
            ),
            ~answered,
        )
        .order_by(Survey.published_at, Survey.created_at)
    )


def answered_since(db: Session, *, user: User, since: datetime) -> bool:
    """Whether this customer has answered any survey from ``since`` on."""
    return (
        db.scalar(
            select(SurveyResponse.id)
            .where(
                SurveyResponse.owner_id == user.id, SurveyResponse.created_at >= since
            )
            .limit(1)
        )
        is not None
    )


def survey_for(db: Session, *, survey_id: str, language: str) -> DueSurvey | None:
    """A live survey's words, or ``None`` once it is closed.

    For a conversation under way (the bot); not held back by «Keyinroq».
    """
    try:
        pk = uuid.UUID(str(survey_id))
    except ValueError:
        return None
    survey = db.scalar(
        select(Survey).where(Survey.id == pk, Survey.is_active.is_(True))
    )
    if survey is None:
        return None
    return _asked(db, survey=survey, language=language)


def _asked(db: Session, *, survey: Survey, language: str) -> DueSurvey:
    lang = language if survey.title.get(language) else survey.source_language
    questions = db.scalars(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey.id)
        .order_by(SurveyQuestion.position)
    )
    return DueSurvey(
        survey_id=str(survey.id),
        language=lang,
        title=survey.title.get(lang, ""),
        intro=survey.intro.get(lang, ""),
        questions=tuple(_question(row, lang) for row in questions),
    )


def _question(row: SurveyQuestion, lang: str) -> AskedQuestion:
    low, high = row.min_value, row.max_value
    return AskedQuestion(
        id=str(row.id),
        position=row.position,
        kind=row.kind,
        text=row.text.get(lang, ""),
        options=tuple(option.get(lang, "") for option in row.options),
        allows_many=row.allows_many,
        numbers=tuple(range(low, high + 1))
        if low is not None and high is not None
        else (),
        is_required=row.is_required,
        show_if=row.show_if or 0,
        show_options=tuple(int(value) for value in row.show_options or ()),
    )
