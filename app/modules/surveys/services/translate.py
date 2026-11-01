"""The worker half of a save: the survey's wording in every other language.

One call for every target language. The answer is written only if it is the
same survey (`core.agent.survey_translation.checked`) and only if the survey has
not been saved again since the call began. Every way it can fail ends the same:
the survey is marked as not translated, and the office asks again or fills the
languages by hand.
"""

import json
import logging
import uuid
from datetime import datetime

from llmkit import LLMError, LLMResult, render
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.exceptions import LLMUnavailable
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMPurpose
from app.modules.surveys.constants import (
    RELATED_TYPE,
    TRANSLATION_PROMPT,
    SurveyState,
)
from app.modules.surveys.languages import language_name, targets
from app.modules.surveys.models import Survey, SurveyQuestion
from core.agent.survey_translation import (
    SurveyLanguage,
    SurveyTranslation,
    TranslationMismatchError,
    checked,
)

logger = logging.getLogger(__name__)


def translate_survey(db: Session, *, survey_id: str, actor_id: str) -> str:
    """Translate and store. Returns a word for the task log."""
    from app.modules.audit.services import record_llm_error, record_llm_result

    survey = db.get(Survey, uuid.UUID(survey_id))
    if survey is None:
        return "gone"
    if survey.state != SurveyState.TRANSLATING:
        return "stale"
    started = survey.updated_at
    actor = db.get(User, uuid.UUID(actor_id))
    languages = targets(survey.source_language)
    if actor is None or not languages:
        return _settle(db, survey, started=started, state=SurveyState.FAILED)
    questions = list(
        db.scalars(
            select(SurveyQuestion)
            .where(SurveyQuestion.survey_id == survey.id)
            .order_by(SurveyQuestion.position)
        )
    )
    try:
        result = _ask(survey, questions, languages)
    except LLMUnavailable:
        logger.warning("survey translation skipped: no Claude in this process")
        return _settle(db, survey, started=started, state=SurveyState.FAILED)
    except LLMError as exc:
        logger.warning("survey translation failed: %s", exc)
        _record_failure(db, survey, actor, exc, record_llm_error)
        return _settle(db, survey, started=started, state=SurveyState.FAILED)
    record_llm_result(
        db,
        owner=actor,
        purpose=LLMPurpose.SURVEY,
        result=result,
        related_type=RELATED_TYPE,
        related_id=survey.id,
    )
    try:
        found = checked(
            result.value,
            languages=languages,
            option_counts=[len(row.options) for row in questions],
            has_intro=bool(survey.intro.get(survey.source_language, "")),
        )
    except TranslationMismatchError as exc:
        logger.warning("survey translation refused: %s", exc)
        return _settle(db, survey, started=started, state=SurveyState.FAILED)
    return _store(db, survey_id=survey.id, started=started, found=found)


def _ask(
    survey: Survey, questions: list[SurveyQuestion], languages: tuple[str, ...]
) -> LLMResult[SurveyTranslation]:
    from app.common.llm import claude, prompts

    lang = survey.source_language
    source = {
        "title": survey.title.get(lang, ""),
        "intro": survey.intro.get(lang, ""),
        "questions": [
            {
                "text": row.text.get(lang, ""),
                "options": [option.get(lang, "") for option in row.options],
            }
            for row in questions
        ],
    }
    template, version = prompts().get(TRANSLATION_PROMPT)
    prompt = render(
        template,
        {
            "source_language": language_name(lang),
            "targets": ", ".join(
                f"{code} ({language_name(code)})" for code in languages
            ),
            "source": json.dumps(source, ensure_ascii=False, indent=2),
        },
    )
    with claude() as client:
        result: LLMResult[SurveyTranslation] = client.structured(
            prompt=prompt,
            schema=SurveyTranslation,
            prompt_name=TRANSLATION_PROMPT,
            prompt_version=version,
        )
    return result


def _store(
    db: Session,
    *,
    survey_id: uuid.UUID,
    started: datetime,
    found: dict[str, SurveyLanguage],
) -> str:
    db.rollback()
    survey = db.get(Survey, survey_id, with_for_update=True, populate_existing=True)
    if survey is None:
        return "gone"
    if survey.state != SurveyState.TRANSLATING or survey.updated_at != started:
        db.rollback()
        return "stale"
    questions = list(
        db.scalars(
            select(SurveyQuestion)
            .where(SurveyQuestion.survey_id == survey.id)
            .order_by(SurveyQuestion.position)
        )
    )
    has_intro = bool(survey.intro.get(survey.source_language, ""))
    title, intro = dict(survey.title), dict(survey.intro)
    for language, item in found.items():
        title[language] = item.title.strip()
        if has_intro:
            intro[language] = item.intro.strip()
        for row, question in zip(questions, item.questions, strict=True):
            row.text = {**row.text, language: question.text.strip()}
            row.options = [
                {**option, language: words.strip()}
                for option, words in zip(row.options, question.options, strict=True)
            ]
    survey.title, survey.intro = title, intro
    survey.state = SurveyState.READY
    db.commit()
    return "ready"


def _settle(
    db: Session, survey: Survey, *, started: datetime, state: SurveyState
) -> str:
    """Mark the end, unless the survey was saved again meanwhile."""
    db.execute(
        update(Survey)
        .where(
            Survey.id == survey.id,
            Survey.state == SurveyState.TRANSLATING,
            Survey.updated_at == started,
        )
        .values(state=state)
    )
    db.commit()
    return str(state)


def _record_failure(
    db: Session, survey: Survey, actor: User, exc: LLMError, record: object
) -> None:
    from app.common.llm import ASKED, model_for, prompts

    _template, version = prompts().get(TRANSLATION_PROMPT)
    record(  # type: ignore[operator]
        db,
        owner=actor,
        purpose=LLMPurpose.SURVEY,
        exc=exc,
        prompt_name=TRANSLATION_PROMPT,
        prompt_version=version,
        model=model_for(ASKED),
        currency=str(settings.anthropic_price_currency),
        related_type=RELATED_TYPE,
        related_id=survey.id,
    )
