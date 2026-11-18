"""The worker half of an office save: the text in the other languages.

One call for every target language (``office_translation``). What comes
back is written only if it is the same text
(``core.agent.office_translation.checked``) and only if the row has not been
saved again since the office pressed. Every way it can fail ends the same:
the row says the translation failed, and the office saves again or writes
the languages by hand. The saved language itself is never touched.
"""

import json
import logging
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from llmkit import LLMError, LLMResult, render
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.exceptions import LLMUnavailable
from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    HELP_LANGUAGES,
    RELATED_ARTICLE,
    RELATED_REFUSAL,
    TRANSLATION_PROMPT,
    TRANSLATION_STUCK_MINUTES,
    Translation,
)
from app.modules.assistant.models import HelpArticle
from app.modules.audit.constants import LLMPurpose
from app.modules.chat.constants import REFUSAL_ANSWER_FIELDS
from app.modules.chat.models import RefusalAnswer
from core.agent.office_translation import (
    OfficeTranslation,
    TranslationMismatchError,
    checked,
)
from core.assistant.prompt import language_name

logger = logging.getLogger(__name__)

ARTICLE_FIELDS = ("problem", "steps")


def shown(state: str, *, since: datetime | None, now: datetime) -> str:
    """The state as the office is told it: a translation no worker finished
    is a failed one, not one to wait for."""
    if state != Translation.TRANSLATING:
        return state
    stuck = since is None or since < now - timedelta(minutes=TRANSLATION_STUCK_MINUTES)
    return Translation.FAILED if stuck else state


def translate_refusal(
    db: Session, *, answer_id: str, actor_id: str, source: str, targets: list[str]
) -> str:
    """Write a refusal answer's other languages. A word for the task log."""
    row = db.get(RefusalAnswer, uuid.UUID(answer_id), populate_existing=True)
    if row is None:
        return "gone"
    if row.translation != Translation.TRANSLATING:
        return "stale"
    started = row.edited_at
    text = getattr(row, REFUSAL_ANSWER_FIELDS[source])
    found = _translated(
        db,
        actor_id=actor_id,
        source=source,
        texts={"answer": text},
        targets=targets,
        related_type=RELATED_REFUSAL,
        related_id=row.id,
    )
    db.rollback()
    row = db.get(RefusalAnswer, row.id, with_for_update=True, populate_existing=True)
    if row is None:
        return "gone"
    if row.translation != Translation.TRANSLATING or row.edited_at != started:
        db.rollback()
        return "stale"
    if found is None:
        row.translation = Translation.FAILED
        db.commit()
        return "failed"
    for language, fields in found.items():
        setattr(row, REFUSAL_ANSWER_FIELDS[language], fields["answer"])
    row.translation = Translation.NONE
    db.commit()
    return "ready"


def translate_article(
    db: Session, *, article_id: str, actor_id: str, source: str, targets: list[str]
) -> str:
    """Write a help article's other languages. A word for the task log."""
    row = db.get(HelpArticle, uuid.UUID(article_id), populate_existing=True)
    if row is None:
        return "gone"
    if row.translation != Translation.TRANSLATING:
        return "stale"
    started = row.updated_at
    texts = {name: getattr(row, f"{name}_{source}") for name in ARTICLE_FIELDS}
    found = _translated(
        db,
        actor_id=actor_id,
        source=source,
        texts=texts,
        targets=targets,
        related_type=RELATED_ARTICLE,
        related_id=row.id,
    )
    db.rollback()
    row = db.get(HelpArticle, row.id, with_for_update=True, populate_existing=True)
    if row is None:
        return "gone"
    if row.translation != Translation.TRANSLATING or row.updated_at != started:
        db.rollback()
        return "stale"
    if found is None:
        row.translation = Translation.FAILED
        db.commit()
        return "failed"
    for language, fields in found.items():
        for name in ARTICLE_FIELDS:
            setattr(row, f"{name}_{language}", fields[name][: _limit(name)])
    row.translation = Translation.NONE
    db.commit()
    return "ready"


def _limit(name: str) -> int:
    from app.modules.assistant.services.articles import PROBLEM_CHARS, STEPS_CHARS

    return PROBLEM_CHARS if name == "problem" else STEPS_CHARS


def _translated(
    db: Session,
    *,
    actor_id: str,
    source: str,
    texts: Mapping[str, str],
    targets: list[str],
    related_type: str,
    related_id: Any,
) -> dict[str, dict[str, str]] | None:
    """The texts in each target language, or nothing when it cannot be had.
    What the call cost is written down either way."""
    from app.common.llm import ASKED, model_for, prompts
    from app.modules.audit.services import record_llm_error, record_llm_result

    actor = db.get(User, uuid.UUID(actor_id))
    wanted = [code for code in targets if code in HELP_LANGUAGES and code != source]
    if actor is None or not wanted or not all(text.strip() for text in texts.values()):
        return None
    template, version = prompts().get(TRANSLATION_PROMPT)
    try:
        result = _ask(template, version, source=source, texts=texts, targets=wanted)
    except LLMUnavailable:
        logger.warning("office translation skipped: no Claude in this process")
        return None
    except LLMError as exc:
        logger.warning("office translation failed: %s", exc)
        record_llm_error(
            db,
            owner=actor,
            purpose=LLMPurpose.OFFICE,
            exc=exc,
            prompt_name=TRANSLATION_PROMPT,
            prompt_version=version,
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            related_type=related_type,
            related_id=related_id,
        )
        db.commit()
        return None
    record_llm_result(
        db,
        owner=actor,
        purpose=LLMPurpose.OFFICE,
        result=result,
        related_type=related_type,
        related_id=related_id,
    )
    db.commit()
    try:
        return checked(result.value, languages=wanted, source=texts)
    except TranslationMismatchError as exc:
        logger.warning("office translation refused: %s", exc)
        return None


def _ask(
    template: str,
    version: str,
    *,
    source: str,
    texts: Mapping[str, str],
    targets: list[str],
) -> LLMResult[OfficeTranslation]:
    from app.common.llm import claude

    prompt = render(
        template,
        {
            "source_language": language_name(source),
            "targets": ", ".join(f"{code} ({language_name(code)})" for code in targets),
            "source": json.dumps(dict(texts), ensure_ascii=False, indent=2),
        },
    )
    with claude() as client:
        result: LLMResult[OfficeTranslation] = client.structured(
            prompt=prompt,
            schema=OfficeTranslation,
            prompt_name=TRANSLATION_PROMPT,
            prompt_version=version,
        )
    return result


__all__ = ["ARTICLE_FIELDS", "shown", "translate_article", "translate_refusal"]
