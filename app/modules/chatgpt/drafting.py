"""«AI yozib bersin» on the ChatGPT form: titles, texts and topics from the profile.

One call while the owner waits, recorded in the LLM ledger like every
other. The answer is trimmed to what OpenAI accepts before it is shown, so
a pick from it never comes back refused.
"""

import logging
from dataclasses import dataclass

from llmkit import LLMError, LLMResult, halves, render
from openaiadskit.launch import BODY_MAX, HINT_MAX, TITLE_MAX, TITLE_MIN
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.llm import ASKED, claude, model_for, prompts
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMCallStatus, LLMPurpose
from app.modules.chatgpt.constants import (
    DRAFT_RELATED_TYPE,
    DRAFT_TIMEOUT_SECONDS,
    PROMPT,
    TURN,
)
from app.modules.chatgpt.exceptions import ChatGPTDraftFailed
from core.agent import ChatGPTCardDraft

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Draft:
    titles: list[str]
    bodies: list[str]
    context_hints: list[str]


def write_draft(db: Session, *, user: User, target_url: str) -> Draft:
    from app.modules.audit.services import record_llm_failure, record_llm_result
    from app.modules.businesses.selectors import business_for

    profile = business_for(db, user)
    try:
        result = _ask(profile=profile, target_url=target_url)
    except LLMError as exc:
        logger.info("chatgpt draft for %s failed: %s", user.id, exc)
        record_llm_failure(
            db,
            owner=user,
            purpose=LLMPurpose.ONBOARDING,
            status=LLMCallStatus.FAILED,
            prompt_name=PROMPT,
            prompt_version=prompts().latest(PROMPT),
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            related_type=DRAFT_RELATED_TYPE,
            related_id=user.id,
        )
        db.commit()
        raise ChatGPTDraftFailed from exc
    record_llm_result(
        db,
        owner=user,
        purpose=LLMPurpose.ONBOARDING,
        result=result,
        related_type=DRAFT_RELATED_TYPE,
        related_id=user.id,
    )
    db.commit()
    return fitted(result.value)


def _ask(*, profile: object, target_url: str) -> LLMResult[ChatGPTCardDraft]:
    from app.modules.businesses.selectors import category_label

    template, version = prompts().get(PROMPT)
    instructions, account = halves(template)
    tail = render(
        account,
        {
            "business_name": getattr(profile, "name", "") or "-",
            "business_category": category_label(profile) if profile else "-",
            "city": getattr(profile, "city", "") or "-",
            "country_code": getattr(profile, "country_code", "") or "UZ",
            "offer_text": getattr(profile, "offer_text", "") or "-",
            "target_url": target_url or getattr(profile, "website", "") or "-",
        },
    )
    with claude(timeout=DRAFT_TIMEOUT_SECONDS) as client:
        return client.structured(
            prompt=TURN,
            system=instructions,
            system_tail=tail,
            schema=ChatGPTCardDraft,
            prompt_name=PROMPT,
            prompt_version=version,
        )


def fitted(draft: ChatGPTCardDraft) -> Draft:
    """The AI's answer with every text OpenAI would refuse left out."""
    return Draft(
        titles=_unique(draft.titles, low=TITLE_MIN, high=TITLE_MAX),
        bodies=_unique(draft.bodies, low=1, high=BODY_MAX),
        context_hints=_unique(draft.context_hints, low=1, high=HINT_MAX),
    )


def _unique(rows: list[str], *, low: int, high: int) -> list[str]:
    kept: list[str] = []
    for row in rows:
        text = " ".join(row.split())
        if low <= len(text) <= high and text.casefold() not in {
            k.casefold() for k in kept
        }:
            kept.append(text)
    return kept
