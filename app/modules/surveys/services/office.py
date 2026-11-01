"""Writing surveys from the office: the survey, its languages, its life.

A survey is written in one language. Only the changed words are translated
again: a save that changes nothing a customer reads - the name, who is asked,
when it runs, which question hangs on which - keeps every language as it is,
the office's own corrections included.

A live or answered survey keeps its questions and conditions: answers already
given are answers to those questions.
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.modules.accounts.models import User
from app.modules.surveys.constants import (
    COPY_SUFFIX,
    NAME_MAX,
    TRANSLATION_STALE_MINUTES,
    SurveyAudience,
    SurveyState,
)
from app.modules.surveys.drafts import LanguageWording, SurveyDraft
from app.modules.surveys.exceptions import (
    SurveyEnded,
    SurveyHasAnswers,
    SurveyIsLive,
    SurveyIsTranslating,
    SurveyNotFound,
    SurveyNotReady,
    TranslationRefused,
)
from app.modules.surveys.languages import all_languages, targets
from app.modules.surveys.models import (
    Survey,
    SurveyQuestion,
    SurveyResponse,
    SurveySighting,
    surveys_people,
    surveys_plans,
)

logger = logging.getLogger(__name__)


def _locked(db: Session, survey_id: uuid.UUID) -> Survey:
    survey = db.get(Survey, survey_id, with_for_update=True)
    if survey is None:
        raise SurveyNotFound
    return survey


def _questions(db: Session, survey_id: uuid.UUID) -> list[SurveyQuestion]:
    return list(
        db.scalars(
            select(SurveyQuestion)
            .where(SurveyQuestion.survey_id == survey_id)
            .order_by(SurveyQuestion.position)
        )
    )


def _answered(db: Session, survey_id: uuid.UUID) -> bool:
    found = select(SurveyResponse.id).where(SurveyResponse.survey_id == survey_id)
    return db.scalar(found.limit(1)) is not None


def _fill(survey: Survey, draft: SurveyDraft) -> None:
    lang = draft.source_language
    survey.source_language = lang
    survey.title = {lang: draft.title.strip()}
    survey.intro = {lang: draft.intro.strip()} if draft.intro.strip() else {}


def _settings(survey: Survey, draft: SurveyDraft) -> None:
    survey.name = draft.name.strip()
    survey.audience = draft.audience.kind
    survey.starts_at = draft.starts_at
    survey.ends_at = draft.ends_at
    survey.ask_after_days = draft.ask_after_days


def _new_questions(survey: Survey, draft: SurveyDraft) -> list[SurveyQuestion]:
    lang = draft.source_language
    return [
        SurveyQuestion(
            survey_id=survey.id,
            position=index,
            kind=question.kind,
            text={lang: question.text.strip()},
            options=[{lang: option.strip()} for option in question.options],
            allows_many=question.allows_many,
            min_value=question.min_value,
            max_value=question.max_value,
            is_required=question.is_required,
            show_if=question.show_if or None,
            show_options=list(question.show_options) if question.show_if else [],
        )
        for index, question in enumerate(draft.questions, start=1)
    ]


def _set_audience(db: Session, survey: Survey, draft: SurveyDraft) -> None:
    """A list the choice does not use is emptied: a survey switched back to
    everyone keeps no stale list that looks as if it mattered."""
    audience = draft.audience
    chosen = audience.kind != SurveyAudience.EVERYONE
    plans = set(audience.plans) if chosen else set()
    people = set(audience.people) if chosen else set()
    db.execute(delete(surveys_plans).where(surveys_plans.c.survey_id == survey.id))
    db.execute(delete(surveys_people).where(surveys_people.c.survey_id == survey.id))
    if plans:
        db.execute(
            insert(surveys_plans),
            [{"survey_id": survey.id, "plan_id": plan} for plan in plans],
        )
    if people:
        db.execute(
            insert(surveys_people),
            [{"survey_id": survey.id, "user_id": person} for person in people],
        )


def _queue_translation(db: Session, survey: Survey, actor: User) -> None:
    """On commit: the worker can start before the words it reads are saved."""
    from app.modules.surveys.tasks import translate_survey_task

    survey_id, actor_id = str(survey.id), str(actor.id)
    on_commit(db, lambda: translate_survey_task.delay(survey_id, actor_id))


def create_survey(db: Session, *, draft: SurveyDraft, actor: User) -> Survey:
    """A new survey sent to be translated. Nobody is asked until it is published."""
    survey = Survey(state=SurveyState.TRANSLATING, is_active=False)
    _fill(survey, draft)
    _settings(survey, draft)
    db.add(survey)
    db.flush()
    _set_audience(db, survey, draft)
    db.add_all(_new_questions(survey, draft))
    db.flush()
    _queue_translation(db, survey, actor)
    logger.info("survey %s created by %s", survey.id, actor.id)
    return survey


def _shape(row: SurveyQuestion, lang: str) -> tuple[object, ...]:
    return (
        row.kind,
        row.text.get(lang, ""),
        tuple(option.get(lang, "") for option in row.options),
        row.allows_many,
        row.min_value,
        row.max_value,
        row.is_required,
    )


def _same_wording(
    survey: Survey, questions: list[SurveyQuestion], draft: SurveyDraft
) -> bool:
    lang = survey.source_language
    if draft.source_language != lang:
        return False
    if survey.title.get(lang, "") != draft.title.strip():
        return False
    if survey.intro.get(lang, "") != draft.intro.strip():
        return False
    fresh = _new_questions(survey, draft)
    return [_shape(row, lang) for row in questions] == [
        _shape(row, lang) for row in fresh
    ]


def _same_rules(questions: list[SurveyQuestion], draft: SurveyDraft) -> bool:
    if len(questions) != len(draft.questions):
        return False
    return all(
        (row.show_if or 0, tuple(row.show_options or ()))
        == (question.show_if, question.show_options if question.show_if else ())
        for row, question in zip(questions, draft.questions, strict=True)
    )


def _check_open(db: Session, survey: Survey) -> None:
    if survey.is_active:
        raise SurveyIsLive(
            "Faol so'rovnomaning savollari o'zgarmaydi. Avval uni yoping."
        )
    if _answered(db, survey.id):
        raise SurveyHasAnswers


def update_survey(
    db: Session, *, survey_id: uuid.UUID, draft: SurveyDraft, actor: User
) -> Survey:
    survey = _locked(db, survey_id)
    if survey.state == SurveyState.TRANSLATING:
        raise SurveyIsTranslating
    questions = _questions(db, survey.id)
    words = _same_wording(survey, questions, draft)
    rules = words and _same_rules(questions, draft)
    if not rules:
        _check_open(db, survey)
    _settings(survey, draft)
    _set_audience(db, survey, draft)
    if words:
        for row, question in zip(questions, draft.questions, strict=True):
            row.show_if = question.show_if or None
            row.show_options = list(question.show_options) if question.show_if else []
        db.flush()
        return survey
    _fill(survey, draft)
    survey.state = SurveyState.TRANSLATING
    db.execute(delete(SurveyQuestion).where(SurveyQuestion.survey_id == survey.id))
    db.add_all(_new_questions(survey, draft))
    db.flush()
    _queue_translation(db, survey, actor)
    logger.info("survey %s rewritten by %s", survey.id, actor.id)
    return survey


def is_complete(survey: Survey, questions: list[SurveyQuestion]) -> bool:
    """Whether every language has every text a customer will read: they are
    shown their own language's words, with none to fall back on."""
    has_intro = bool(survey.intro.get(survey.source_language, ""))
    for lang in all_languages():
        if not survey.title.get(lang, "").strip():
            return False
        if has_intro and not survey.intro.get(lang, "").strip():
            return False
        for row in questions:
            if not row.text.get(lang, "").strip():
                return False
            if any(not option.get(lang, "").strip() for option in row.options):
                return False
    return True


def publish_survey(
    db: Session, *, survey_id: uuid.UUID, actor: User, now: datetime
) -> Survey:
    """Start asking it, from `starts_at` when one is set. Others stay live."""
    survey = _locked(db, survey_id)
    if survey.state != SurveyState.READY or not is_complete(
        survey, _questions(db, survey.id)
    ):
        raise SurveyNotReady
    if survey.ends_at is not None and survey.ends_at <= now:
        raise SurveyEnded
    survey.is_active = True
    survey.published_at = now
    db.flush()
    logger.info("survey %s published by %s", survey.id, actor.id)
    return survey


def stop_survey(db: Session, *, survey_id: uuid.UUID, actor: User) -> Survey:
    """Nobody else is asked. Answers already given stay."""
    survey = _locked(db, survey_id)
    survey.is_active = False
    db.flush()
    logger.info("survey %s stopped by %s", survey.id, actor.id)
    return survey


def retry_translation(
    db: Session, *, survey_id: uuid.UUID, actor: User, now: datetime
) -> Survey:
    """After a failure or a run that never came back. From a finished one it
    replaces what was corrected by hand; a live survey keeps its words."""
    survey = _locked(db, survey_id)
    if survey.is_active:
        raise SurveyIsLive
    lost = now - timedelta(minutes=TRANSLATION_STALE_MINUTES)
    if survey.state == SurveyState.TRANSLATING and survey.updated_at > lost:
        raise SurveyIsTranslating
    survey.state = SurveyState.TRANSLATING
    survey.updated_at = now
    db.flush()
    _queue_translation(db, survey, actor)
    return survey


def save_translation(
    db: Session,
    *,
    survey_id: uuid.UUID,
    language: str,
    wording: LanguageWording,
    actor: User,
) -> Survey:
    """One language's words over the translation. The questions and options
    are the source's, so the wording has to fit them one for one. A live survey
    may be corrected: a typo is fixed where it is read. Filling the last empty
    language by hand is how a failed translation becomes ready."""
    survey = _locked(db, survey_id)
    if survey.state == SurveyState.TRANSLATING:
        raise SurveyIsTranslating
    if language not in targets(survey.source_language):
        raise TranslationRefused
    questions = _questions(db, survey.id)
    if len(wording.questions) != len(questions):
        raise TranslationRefused
    for row, words in zip(questions, wording.questions, strict=True):
        if len(words.options) != len(row.options):
            raise TranslationRefused
    survey.title = {**survey.title, language: wording.title.strip()}
    intro = {**survey.intro}
    if wording.intro.strip():
        intro[language] = wording.intro.strip()
    else:
        intro.pop(language, None)
    survey.intro = intro
    for row, words in zip(questions, wording.questions, strict=True):
        row.text = {**row.text, language: words.text.strip()}
        row.options = [
            {**option, language: text.strip()}
            for option, text in zip(row.options, words.options, strict=True)
        ]
    if survey.state == SurveyState.FAILED and is_complete(survey, questions):
        survey.state = SurveyState.READY
    db.flush()
    logger.info("survey %s %s corrected by %s", survey.id, language, actor.id)
    return survey


def delete_survey(db: Session, *, survey_id: uuid.UUID, actor: User) -> None:
    """Remove a survey nobody is asked or has answered, with its questions."""
    survey = _locked(db, survey_id)
    if survey.is_active:
        raise SurveyIsLive
    if _answered(db, survey.id):
        raise SurveyHasAnswers
    db.execute(delete(SurveySighting).where(SurveySighting.survey_id == survey.id))
    db.execute(delete(SurveyQuestion).where(SurveyQuestion.survey_id == survey.id))
    db.execute(delete(surveys_plans).where(surveys_plans.c.survey_id == survey.id))
    db.execute(delete(surveys_people).where(surveys_people.c.survey_id == survey.id))
    db.delete(survey)
    db.flush()
    logger.info("survey %s deleted by %s", survey_id, actor.id)


def _copy_audience(db: Session, *, source_id: uuid.UUID, copy_id: uuid.UUID) -> None:
    plans = db.scalars(
        select(surveys_plans.c.plan_id).where(surveys_plans.c.survey_id == source_id)
    ).all()
    people = db.scalars(
        select(surveys_people.c.user_id).where(surveys_people.c.survey_id == source_id)
    ).all()
    if plans:
        db.execute(
            insert(surveys_plans),
            [{"survey_id": copy_id, "plan_id": plan} for plan in plans],
        )
    if people:
        db.execute(
            insert(surveys_people),
            [{"survey_id": copy_id, "user_id": person} for person in people],
        )


def duplicate_survey(
    db: Session,
    *,
    survey_id: uuid.UUID,
    actor: User,
    name: str = "",
    keep_audience: bool = False,
) -> Survey:
    """A closed copy with every language kept, so nothing is translated again.
    A copy is made to go to someone else, so who was asked stays behind unless
    the office says otherwise. Its dates belonged to the original and never come."""
    source = db.get(Survey, survey_id)
    if source is None:
        raise SurveyNotFound
    name = name.strip() or f"{source.name[: NAME_MAX - len(COPY_SUFFIX)]}{COPY_SUFFIX}"
    copy = Survey(
        name=name,
        audience=source.audience if keep_audience else SurveyAudience.EVERYONE,
        source_language=source.source_language,
        title=dict(source.title),
        intro=dict(source.intro),
        ask_after_days=source.ask_after_days,
        state=(
            SurveyState.READY
            if source.state == SurveyState.READY
            else SurveyState.FAILED
        ),
        is_active=False,
    )
    db.add(copy)
    db.flush()
    db.add_all(
        SurveyQuestion(
            survey_id=copy.id,
            position=row.position,
            kind=row.kind,
            text=dict(row.text),
            options=[dict(option) for option in row.options],
            allows_many=row.allows_many,
            min_value=row.min_value,
            max_value=row.max_value,
            is_required=row.is_required,
            show_if=row.show_if,
            show_options=list(row.show_options or []),
        )
        for row in _questions(db, source.id)
    )
    if keep_audience:
        _copy_audience(db, source_id=source.id, copy_id=copy.id)
    db.flush()
    logger.info("survey %s copied to %s by %s", source.id, copy.id, actor.id)
    return copy
