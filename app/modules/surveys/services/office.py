"""Writing surveys from the office: the survey, its languages, its life.

A survey is written in one language. Only the changed words are translated
again: a save that changes nothing a customer reads - the name, who is asked,
when it runs, which question hangs on which - keeps every language as it is,
the office's own corrections included.

A live or answered survey may be edited too: whoever finished it is not asked
again, whoever is added or has not finished gets the edited one. A question
keeps its id - and the answers and «yordam kerak» marks hung on it - while it
keeps its kind, its number of options and its scale; otherwise it is a new
question. Every answer already kept carries the question and answer as they
were read, so a removed or reworded question still reads as it was answered.

Deleting closes a survey and takes it out of the office's list; nothing is
removed from the database.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.surveys.constants import (
    COPY_SUFFIX,
    NAME_MAX,
    TRANSLATION_STALE_MINUTES,
    SurveyAudience,
    SurveyState,
)
from app.modules.surveys.drafts import LanguageWording, QuestionDraft, SurveyDraft
from app.modules.surveys.exceptions import (
    SurveyEnded,
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
    surveys_people,
    surveys_plans,
)
from app.modules.surveys.selectors.office import office_language, shown

logger = logging.getLogger(__name__)


def _locked(db: Session, survey_id: uuid.UUID) -> Survey:
    survey = db.get(Survey, survey_id, with_for_update=True)
    if survey is None or survey.deleted_at is not None:
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


def _written(question: QuestionDraft, *, lang: str, position: int) -> dict[str, Any]:
    """A question's columns as the office wrote it, in the source language."""
    return {
        "position": position,
        "kind": question.kind,
        "text": {lang: question.text.strip()},
        "options": [{lang: option.strip()} for option in question.options],
        "allows_many": question.allows_many,
        "min_value": question.min_value,
        "max_value": question.max_value,
        "is_required": question.is_required,
        "show_if": question.show_if or None,
        "show_options": list(question.show_options) if question.show_if else [],
    }


def _new_questions(survey: Survey, draft: SurveyDraft) -> list[SurveyQuestion]:
    lang = draft.source_language
    return [
        SurveyQuestion(
            survey_id=survey.id, **_written(question, lang=lang, position=index)
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


def update_survey(
    db: Session, *, survey_id: uuid.UUID, draft: SurveyDraft, actor: User
) -> Survey:
    """Save the office's edit, live or answered alike. Changed words are
    translated again; meanwhile a reader in another language reads the source."""
    survey = _locked(db, survey_id)
    if survey.state == SurveyState.TRANSLATING:
        raise SurveyIsTranslating
    questions = _questions(db, survey.id)
    words = _same_wording(survey, questions, draft)
    _settings(survey, draft)
    _set_audience(db, survey, draft)
    if words:
        for row, question in zip(questions, draft.questions, strict=True):
            row.show_if = question.show_if or None
            row.show_options = list(question.show_options) if question.show_if else []
        db.flush()
        return survey
    _freeze_answers(db, survey, questions)
    _fill(survey, draft)
    survey.state = SurveyState.TRANSLATING
    _rewrite_questions(db, survey, questions, draft)
    _queue_translation(db, survey, actor)
    logger.info("survey %s rewritten by %s", survey.id, actor.id)
    return survey


def _same_question(row: SurveyQuestion, question: QuestionDraft) -> bool:
    """Whether a kept answer still means the same: the same kind, as many
    options, the same scale."""
    return (
        row.kind == question.kind
        and len(row.options) == len(question.options)
        and row.min_value == question.min_value
        and row.max_value == question.max_value
    )


def _rewrite_questions(
    db: Session,
    survey: Survey,
    questions: list[SurveyQuestion],
    draft: SurveyDraft,
) -> None:
    """The draft's questions over the saved ones, each kept by its id while it
    still means the same. Positions are unique, so the kept ones step aside
    first."""
    lang = draft.source_language
    by_id = {str(row.id): row for row in questions}
    kept: list[tuple[SurveyQuestion, QuestionDraft, int]] = []
    fresh: list[tuple[QuestionDraft, int]] = []
    for position, question in enumerate(draft.questions, start=1):
        row = by_id.get(question.id) if question.id else None
        if row is not None and _same_question(row, question):
            del by_id[question.id]
            kept.append((row, question, position))
        else:
            fresh.append((question, position))
    gone = [row.id for row in by_id.values()]
    if gone:
        db.execute(delete(SurveyQuestion).where(SurveyQuestion.id.in_(gone)))
    for index, (row, _, _) in enumerate(kept, start=1):
        row.position = -index
    db.flush()
    for row, question, position in kept:
        for column, value in _written(question, lang=lang, position=position).items():
            setattr(row, column, value)
    db.add_all(
        SurveyQuestion(
            survey_id=survey.id, **_written(question, lang=lang, position=position)
        )
        for question, position in fresh
    )
    db.flush()


def _freeze_answers(
    db: Session, survey: Survey, questions: list[SurveyQuestion]
) -> None:
    """Write the question and the answer, as read today, into every kept
    answer that does not carry them yet: its question may change next."""
    lang = office_language(survey)
    by_id = {str(row.id): row for row in questions}
    for response in db.scalars(
        select(SurveyResponse).where(SurveyResponse.survey_id == survey.id)
    ):
        items = []
        changed = False
        for item in response.answers or []:
            row = by_id.get(str(item.get("question")))
            if row is not None and "q" not in item:
                item = {
                    **item,
                    "q": row.text.get(lang, ""),
                    "a": shown(row, item, lang),
                }
                changed = True
            items.append(item)
        if changed:
            response.answers = items
    db.flush()


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
    replaces what was corrected by hand. A live survey may be retried too: an
    edit made while it is live is translated the same way."""
    survey = _locked(db, survey_id)
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


def delete_survey(
    db: Session, *, survey_id: uuid.UUID, actor: User, now: datetime | None = None
) -> Survey:
    """Close it and take it out of the office's list. Its questions, who it
    was for and every answer stay in the database."""
    survey = _locked(db, survey_id)
    survey.is_active = False
    survey.deleted_at = now or utcnow()
    db.flush()
    logger.info("survey %s deleted by %s", survey_id, actor.id)
    return survey


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
    if source is None or source.deleted_at is not None:
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
