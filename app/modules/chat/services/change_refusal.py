"""Why Meta refused a change to a running advert: asked of Claude once, kept for everyone.

No chat and no button. The first time a refusal with a code nobody has an
answer for reaches a screen, the worker asks Claude; the answer is kept under
Meta's code and subcode, in the reader's language, and every later owner who
meets the same refusal reads it at once. The office edits and translates it.
"""

import logging
import uuid

from llmkit import LLMError, render
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.exceptions import LLMUnavailable
from app.common.llm import ASKED, claude, model_for, prompts
from app.modules.audit.constants import ActionStatus, LLMPurpose
from app.modules.audit.models import ActionLog
from app.modules.chat.constants import (
    CHANGE_REFUSAL_LOCK_SECONDS,
    CHANGE_REFUSAL_PROMPT_NAME,
    CHANGE_REFUSAL_VERSION_PREFIX,
    REFUSAL_MAX_TOKENS,
)
from app.modules.chat.selectors.change_refusal import (
    change_explanation,
    change_facts,
    change_key,
)
from app.modules.chat.selectors.refusal import answer_language
from app.modules.chat.services.refusal import keep_answer
from core.chat.refusal import shareable
from core.chat.verify import FigureGate

logger = logging.getLogger(__name__)

ASK = "Explain this refusal and write the steps."
LOCK = "change-refusal:{key}:{language}"
RELATED = "action_log"


def explain_later(*, log: ActionLog, language: str) -> bool:
    """Send the refusal to be explained, once per code and language. False: it cannot be."""
    from app.modules.chat.tasks import explain_change_refusal

    key = change_key(log)
    if not key:
        return False
    language = answer_language(language)
    if cache.add(
        LOCK.format(key=key, language=language), 1, CHANGE_REFUSAL_LOCK_SECONDS
    ):
        explain_change_refusal.delay(str(log.id), language)
    return True


def explain_change(db: Session, *, log_id: str, language: str) -> str:
    """The kept answer, or a new one asked of Claude and kept. Empty when there is none."""
    from app.modules.audit.services import record_llm_error, record_llm_result

    try:
        log = db.get(ActionLog, uuid.UUID(str(log_id)))
    except ValueError:
        log = None
    if log is None or log.status != ActionStatus.FAILED:
        return ""
    key = change_key(log)
    language = answer_language(language)
    if not key:
        return ""
    ready = change_explanation(db, log=log, language=language)
    if ready:
        return ready
    facts = change_facts(log)
    gate = FigureGate(allowed=facts.figures())
    template, version = prompts().get(CHANGE_REFUSAL_PROMPT_NAME)
    system = render(template, {"language": language, "facts": facts.render()})
    try:
        with claude() as client:
            stream = client.stream(
                prompt=ASK,
                system=system,
                prompt_name=CHANGE_REFUSAL_PROMPT_NAME,
                prompt_version=version,
                max_tokens=REFUSAL_MAX_TOKENS,
            )
            safe = [gate.feed(piece) for piece in stream]
            safe.append(gate.flush())
    except LLMUnavailable:
        logger.warning("change refusal not explained: no Claude in this process")
        return ""
    except LLMError as exc:
        logger.warning("change refusal not explained: %s", exc)
        record_llm_error(
            db,
            owner=log.owner,
            purpose=LLMPurpose.REFUSAL,
            exc=exc,
            prompt_name=CHANGE_REFUSAL_PROMPT_NAME,
            prompt_version=version,
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            related_type=RELATED,
            related_id=str(log.id),
        )
        return ""
    text = "".join(safe).strip()
    record_llm_result(
        db,
        owner=log.owner,
        purpose=LLMPurpose.REFUSAL,
        result=stream.result,
        masked=gate.masked,
        related_type=RELATED,
        related_id=str(log.id),
    )
    if not text or gate.masked or not shareable(text):
        # An answer with this owner's figures in it cannot be shown to the
        # next one; the screen keeps its own sentence.
        return ""
    keep_answer(
        db,
        key=key,
        language=language,
        text=text,
        facts=facts,
        version=f"{CHANGE_REFUSAL_VERSION_PREFIX}{version}",
    )
    return text


__all__ = ["explain_change", "explain_later"]
