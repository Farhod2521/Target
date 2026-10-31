"""Why Meta refused a launch or a change: asked of Claude once, kept for everyone.

No chat and no button. The first time a refusal with a code nobody has an
answer for reaches a screen, the worker asks Claude once, for all three
languages; the answer is kept under the refusal's key and every later owner
who meets the same refusal reads it at once. The office edits it.

A launch and a change to a running advert are kept apart (``meta:...`` and
``change:meta:...``): the same code means the same thing, but a launch is
retried from its page and a change from the campaigns screen.
"""

import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import asdict

from llmkit import LLMError, render
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.exceptions import LLMUnavailable
from app.common.llm import ASKED, claude, model_for, prompts
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.audit.constants import ActionStatus, LLMPurpose
from app.modules.audit.models import ActionLog
from app.modules.chat.constants import (
    ACTION_REFUSAL_PROMPT_NAME,
    ACTION_REFUSAL_VERSION_PREFIX,
    CHANGE_REFUSAL_PROMPT_NAME,
    CHANGE_REFUSAL_VERSION_PREFIX,
    REFUSAL_EVERY_LANGUAGE,
    REFUSAL_GAVE_UP,
    REFUSAL_GAVE_UP_SECONDS,
    REFUSAL_LOCK,
    REFUSAL_LOCK_SECONDS,
    REFUSAL_PROMPT_NAME,
)
from app.modules.chat.models import RefusalAnswer
from app.modules.chat.selectors.change_refusal import change_facts, change_key
from app.modules.chat.selectors.refusal import (
    already_asked,
    answer_language,
    explained_key,
    ready_answer,
    refusal_facts,
    refused_launch_for,
)
from app.modules.chat.services.refusal import keep_answer
from core.chat.refusal import ChangeFacts, RefusalFacts, shareable
from core.chat.verify import FigureGate

logger = logging.getLogger(__name__)

ASK = "Explain this refusal and write the steps."


class RefusalAnswers(BaseModel):
    """One refusal explained in every language an owner reads."""

    uz: str = Field(description="The whole answer in Uzbek, in Latin script.")
    ru: str = Field(description="The whole answer in Russian.")
    en: str = Field(description="The whole answer in English.")


def explain_later(*, log: ActionLog, language: str) -> bool:
    """Send a refused change to be explained, once per key and language. False: it cannot be."""
    from app.modules.chat.tasks import explain_change_refusal

    return _send(change_key(log), language, explain_change_refusal, str(log.id))


def explain_launch_later(*, launch: CampaignLaunch, language: str) -> bool:
    """Send a refused launch to be explained, once per key and language. False: it cannot be."""
    from app.modules.chat.tasks import explain_launch_refusal

    return _send(
        explained_key(launch), language, explain_launch_refusal, str(launch.id)
    )


def explain_action_later(
    *, key: str, owner: User, facts: ChangeFacts, language: str
) -> None:
    """Send a refused press to be explained. Nothing is stored to read it back from."""
    from app.modules.chat.tasks import explain_action_refusal

    payload = {"key": key, "owner_id": str(owner.id), "facts": asdict(facts)}
    _send(key, language, explain_action_refusal, json.dumps(payload))


def _send(key: str, language: str, task: object, pk: str) -> bool:
    if not key:
        return False
    if cache.add(REFUSAL_LOCK.format(key=key), 1, REFUSAL_LOCK_SECONDS):
        task.delay(pk, answer_language(language))  # type: ignore[attr-defined]
    return True


def count_refusal(db: Session, *, key: str) -> None:
    """One more owner met this refusal, for the office's list."""
    db.execute(
        update(RefusalAnswer)
        .where(RefusalAnswer.key == key)
        .values(hits=RefusalAnswer.hits + 1)
    )


def explain_change(db: Session, *, log_id: str, language: str) -> str:
    """The kept answer, or a new one asked of Claude and kept. Empty when there is none."""
    try:
        log = db.get(ActionLog, uuid.UUID(str(log_id)))
    except ValueError:
        log = None
    if log is None or log.status != ActionStatus.FAILED:
        return ""
    return _answer(
        db,
        owner=log.owner,
        key=change_key(log),
        language=language,
        facts=change_facts(log),
        prompt_name=CHANGE_REFUSAL_PROMPT_NAME,
        version_prefix=CHANGE_REFUSAL_VERSION_PREFIX,
        related=("action_log", str(log.id)),
    )


def explain_action(db: Session, *, payload: str, language: str) -> str:
    """The same for a refused press, from what was known when it was refused."""
    asked = json.loads(payload)
    owner = db.get(User, uuid.UUID(asked["owner_id"]))
    if owner is None:
        return ""
    facts = dict(asked["facts"])
    facts["links"] = tuple(tuple(link) for link in facts["links"])
    return _answer(
        db,
        owner=owner,
        key=asked["key"],
        language=language,
        facts=ChangeFacts(**facts),
        prompt_name=ACTION_REFUSAL_PROMPT_NAME,
        version_prefix=ACTION_REFUSAL_VERSION_PREFIX,
        related=("refusal", asked["key"]),
    )


def explain_launch(db: Session, *, launch_id: str, language: str) -> str:
    """The same for a refused launch, under the launch prompt the chat answers with."""
    try:
        found = db.get(CampaignLaunch, uuid.UUID(str(launch_id)))
    except ValueError:
        found = None
    owner = found.owner if found is not None else None
    launch = (
        refused_launch_for(db, owner=owner, launch_id=launch_id)
        if owner is not None
        else None
    )
    if owner is None or launch is None:
        return ""
    return _answer(
        db,
        owner=owner,
        key=explained_key(launch),
        language=language,
        facts=refusal_facts(launch),
        prompt_name=REFUSAL_PROMPT_NAME,
        version_prefix="",
        related=("campaign_launch", str(launch.id)),
    )


def _answer(
    db: Session,
    *,
    owner: User,
    key: str,
    language: str,
    facts: ChangeFacts | RefusalFacts,
    prompt_name: str,
    version_prefix: str,
    related: tuple[str, str],
) -> str:
    from app.modules.audit.services import record_llm_error, record_llm_result

    language = answer_language(language)
    if not key:
        return ""
    ready = ready_answer(db, key=key, language=language)
    if ready is not None:
        return ready.text
    if already_asked(db, key=key):
        _gave_up(key)
        return ""
    template, version = prompts().get(prompt_name)
    system = render(
        template, {"language": REFUSAL_EVERY_LANGUAGE, "facts": facts.render()}
    )
    related_type, related_id = related
    try:
        with claude() as client:
            result = client.structured(
                prompt=ASK,
                schema=RefusalAnswers,
                system=system,
                prompt_name=prompt_name,
                prompt_version=version,
            )
    except LLMUnavailable:
        logger.warning("refusal not explained: no Claude in this process")
        _gave_up(key)
        return ""
    except LLMError as exc:
        logger.warning("refusal not explained: %s", exc)
        record_llm_error(
            db,
            owner=owner,
            purpose=LLMPurpose.REFUSAL,
            exc=exc,
            prompt_name=prompt_name,
            prompt_version=version,
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            related_type=related_type,
            related_id=related_id,
        )
        _gave_up(key)
        return ""
    texts = {name: text.strip() for name, text in result.value.model_dump().items()}
    masked = _masked(texts, facts)
    record_llm_result(
        db,
        owner=owner,
        purpose=LLMPurpose.REFUSAL,
        result=result,
        masked=masked,
        related_type=related_type,
        related_id=related_id,
    )
    if not all(texts.values()):
        _gave_up(key)
        return ""
    # An answer with this owner's figures in it cannot be shown to the next
    # one. It is kept for the office to correct, so Claude is not asked again.
    held = bool(masked) or not all(shareable(text) for text in texts.values())
    keep_answer(
        db,
        key=key,
        texts=texts,
        facts=facts,
        version=f"{version_prefix}{version}",
        held=held,
    )
    if held:
        _gave_up(key)
        return ""
    return texts[language]


def _masked(texts: Mapping[str, str], facts: ChangeFacts | RefusalFacts) -> int:
    """How many figures in these answers Claude was not handed."""
    masked = 0
    for text in texts.values():
        gate = FigureGate(allowed=facts.figures())
        gate.feed(text)
        gate.flush()
        masked += gate.masked
    return masked


def _gave_up(key: str) -> None:
    cache.set(REFUSAL_LOCK.format(key=key), REFUSAL_GAVE_UP, REFUSAL_GAVE_UP_SECONDS)


__all__ = [
    "count_refusal",
    "explain_action",
    "explain_action_later",
    "explain_change",
    "explain_later",
    "explain_launch",
    "explain_launch_later",
]
