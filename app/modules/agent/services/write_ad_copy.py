"""New words for an advert the platform refused under a policy."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

from llmkit import LLMError, render
from sqlalchemy.orm import Session

from app.common.llm import claude, prompts
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdCreative
from app.modules.ads.selectors.actions import managed_target
from app.modules.ads.selectors.copy_notes import NO_BUTTON, button_action, offer_text
from app.modules.ads.selectors.creatives import creative_of
from app.modules.ads.selectors.launched import adset_launch, campaign_launch
from app.modules.agent.constants import (
    NO_WORDS_PREFIX,
    RUN_RELATED_TYPE,
    SuggestionKind,
)
from app.modules.agent.models import AgentRun
from app.modules.agent.services.check_review import Reviewed
from app.modules.audit.constants import LLMPurpose
from app.modules.audit.services import record_llm_result
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import category_label
from core.agent import CreativeProposal, Finding
from core.agent.copy_check import AdWords, check_against_offer

logger = logging.getLogger(__name__)
PROMPT: Final = "ad_refresh"
_REFUSED: Final = (
    "Meta refused this advert under its advertising policies and it is not "
    "being shown. Meta's words: {refusal}"
)


class _NoWordsError(Exception):
    """Why one advert gets no new words - and so no proposal."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _Sources:
    """What new words for one advert are written from."""

    creative: AdCreative
    offer: str
    sends_to: str
    facts: str


def writable(
    db: Session,
    *,
    user: User,
    run: AgentRun,
    business: Business,
    findings: list[Finding],
) -> list[Finding]:
    """The findings worth paying a review for - every new advert left out
    that no call could write words for."""
    kept: list[Finding] = []
    for finding in findings:
        if finding.kind == SuggestionKind.NEW_AD:
            try:
                _sources(db, user=user, business=business, finding=finding)
            except _NoWordsError as gap:
                _drop(run=run, finding=finding, code=gap.code)
                continue
        kept.append(finding)
    return kept


def with_ad_copy(
    db: Session,
    *,
    user: User,
    run: AgentRun,
    business: Business,
    reviewed: list[Reviewed],
) -> list[Reviewed]:
    """The kept findings, each new advert carrying its words - or left out."""
    kept: list[Reviewed] = []
    for item in reviewed:
        if item.finding.kind != SuggestionKind.NEW_AD:
            kept.append(item)
            continue
        try:
            words = _written(
                db, user=user, run=run, business=business, finding=item.finding
            )
        except _NoWordsError as gap:
            _drop(run=run, finding=item.finding, code=gap.code)
            continue
        kept.append(replace(item, finding=replace(item.finding, payload=words)))
    return kept


def _drop(*, run: AgentRun, finding: Finding, code: str) -> None:
    logger.warning(
        "agent_ad_copy_dropped",
        extra={"run": str(run.id), "ad": finding.ref.id, "code": code},
    )
    run.dropped = [
        *(run.dropped or []),
        {
            "rule": finding.rule,
            "target": finding.ref.id,
            "reason": f"{NO_WORDS_PREFIX}{code}",
        },
    ]


def _sources(
    db: Session, *, user: User, business: Business, finding: Finding
) -> _Sources:
    """What the words are written from. Raises :class:`_NoWordsError`."""
    ad = managed_target(db, owner=user, level="ad", external_id=finding.ref.id)
    creative = creative_of(db, owner=user, ad=ad) if isinstance(ad, Ad) else None
    if not isinstance(ad, Ad) or creative is None or not creative.story_raw:
        raise _NoWordsError("no_story")
    launch = adset_launch(
        db, owner=user, adset_external_id=ad.adset.external_id
    ) or campaign_launch(
        db, owner=user, campaign_external_id=ad.adset.campaign.external_id
    )
    offer = (
        offer_text(db, launch=launch, business=business)
        if launch is not None
        else str(business.offer_text or "")
    )
    sends_to = button_action(db, launch=launch) if launch is not None else NO_BUTTON
    facts = "\n".join(part for part in (offer, creative.message) if part)
    if not facts.strip():
        raise _NoWordsError("no_offer")
    return _Sources(creative=creative, offer=offer, sends_to=sends_to, facts=facts)


def _written(
    db: Session, *, user: User, run: AgentRun, business: Business, finding: Finding
) -> dict[str, str]:
    """Words for one advert. Raises :class:`_NoWordsError` with the reason."""
    sources = _sources(db, user=user, business=business, finding=finding)
    proposal = _ask(
        db,
        user=user,
        run=run,
        variables=_variables(
            business=business,
            finding=finding,
            creative=sources.creative,
            offer=sources.offer,
            sends_to=sources.sends_to,
        ),
    )
    if proposal is None:
        raise _NoWordsError("ai_failed")
    words = AdWords(
        primary_text=proposal.primary_text,
        headline=proposal.headline,
        description=proposal.description,
    )
    problems = check_against_offer(
        words=words, facts=sources.facts, sends_to=sources.sends_to
    )
    if problems:
        raise _NoWordsError(",".join(problem.code for problem in problems))
    return {
        "message": words.primary_text,
        "headline": words.headline,
        "description": words.description,
    }


def _ask(
    db: Session, *, user: User, run: AgentRun, variables: dict[str, str]
) -> CreativeProposal | None:
    """One call, recorded against the run it was made for."""
    template, version = prompts().get(PROMPT)
    try:
        with claude() as client:
            result = client.structured(
                prompt=render(template, variables),
                schema=CreativeProposal,
                prompt_name=PROMPT,
                prompt_version=version,
            )
    except LLMError:
        logger.warning("agent_ad_copy_failed", extra={"run": str(run.id)})
        return None
    record_llm_result(
        db,
        owner=user,
        purpose=LLMPurpose.DECISION,
        result=result,
        related_type=RUN_RELATED_TYPE,
        related_id=run.id,
    )
    run.llm_cost_minor = (run.llm_cost_minor or 0) + result.cost_minor
    return result.value


def _variables(
    *,
    business: Business,
    finding: Finding,
    creative: AdCreative,
    offer: str,
    sends_to: str,
) -> dict[str, str]:
    """Everything the prompt may know, assembled explicitly."""
    return {
        "business_name": business.name,
        "business_category": category_label(business),
        "city": business.city or "-",
        "offer_text": offer or "-",
        "button_action": sends_to,
        "current_primary_text": creative.message or "-",
        "current_headline": creative.headline or "-",
        "current_description": creative.description or "-",
        "what_is_wrong": _what_is_wrong(finding.evidence),
    }


def _what_is_wrong(evidence: Mapping[str, Any]) -> str:
    """The paragraph the words are written against: the platform's refusal."""
    return _REFUSED.format(refusal=str(evidence.get("refusal", "")).strip())


__all__ = ["PROMPT", "with_ad_copy", "writable"]
