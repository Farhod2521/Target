"""One section of a proposal written again, and the answers a written question offers."""

import json
import logging
from typing import Any
from uuid import UUID

from llmkit import (
    ClaudeRateLimited,
    ClaudeTemporaryError,
    LLMError,
    StructuredOutputError,
    render,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import on_commit, utcnow
from app.common.llm import ASKED, claude, model_for, prompts
from app.modules.ads import audiences as audience_field
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    BUILD_PROGRESS,
    LAUNCH_RELATED_TYPE,
    WRITING_TIMEOUT_SECONDS,
    DraftSection,
    FormDepth,
    InterestSource,
    LaunchStatus,
    LaunchStep,
)
from app.modules.ads.exceptions import (
    AlreadyRegenerated,
    DraftNotReady,
    PreparationRunning,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.lead_form import (
    form_depth,
    form_variables,
    question_limit,
)
from app.modules.audit.constants import LLMPurpose
from app.modules.billing.exceptions import NoEntitlement
from app.modules.businesses.models import Business
from core.agent import (
    AudienceProposal,
    CreativeSection,
    DeepFormSection,
    FormSection,
    InterestSection,
    QuestionOptions,
)

logger = logging.getLogger(__name__)
RELATED_TYPE = LAUNCH_RELATED_TYPE
SECTIONS: dict[str, tuple[str, type[BaseModel], str]] = {
    DraftSection.AUDIENCE: ("audience_section", AudienceProposal, "previous_audience"),
    DraftSection.INTERESTS: (
        "interests_section",
        InterestSection,
        "previous_interests",
    ),
    DraftSection.CREATIVE: ("creative_section", CreativeSection, "previous_creative"),
    DraftSection.FORM: ("form_section", FormSection, "previous_questions"),
}
PURPOSES = {DraftSection.FORM: LLMPurpose.FORM_BUILD}
KEPT_ON_REGENERATE: tuple[str, ...] = (
    geo_field.GEO_KEY,
    "targeting_mode",
    "placement_mode",
    "placement_positions",
    audience_field.AUDIENCES_KEY,
)
OPTIONS_PROMPT = "form_options"
PENDING = "options_pending"


def _business(db: Session, launch: CampaignLaunch) -> Business | None:
    from app.modules.businesses.selectors import business_for_page

    return business_for_page(db, owner=launch.owner, page=launch.page)


def request_regeneration(db: Session, *, launch: CampaignLaunch, section: str) -> None:
    """Check the one-per-section rule, then queue the call. Commits."""
    from app.modules.ads.tasks import regenerate_section_task
    from app.modules.billing.services import require_preparation

    if section not in SECTIONS:
        raise ValueError(f"not a draft section: {section!r}")
    require_preparation(db, owner=launch.owner)
    if launch.status == LaunchStatus.BUILDING:
        raise PreparationRunning
    if launch.status != LaunchStatus.READY or not launch.draft:
        raise DraftNotReady
    if draft_field.was_regenerated(launch.draft, section):
        raise AlreadyRegenerated
    launch.status = str(LaunchStatus.BUILDING)
    launch.step = str(LaunchStep.ASKING)
    launch.progress = BUILD_PROGRESS[LaunchStep.ASKING][0]
    launch.error_code = ""
    launch.started_at = utcnow()
    launch_id = str(launch.id)
    on_commit(db, lambda: regenerate_section_task.delay(launch_id, section))
    db.commit()


def regenerate_section(db: Session, *, launch_id: UUID | str, section: str) -> str:
    """The worker half. Returns a word for the task log."""
    from app.modules.ads.services.proposal import review_copy
    from app.modules.audit.services import record_llm_result
    from app.modules.billing.services import require_preparation

    if section not in SECTIONS:
        return "unknown section"
    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    try:
        require_preparation(db, owner=launch.owner)
    except NoEntitlement:
        return _fail(db, launch, code="subscription_expired")
    business = _business(db, launch)
    if business is None:
        return _fail(db, launch, code="profile_incomplete")
    prompt_name, schema, _previous = SECTIONS[section]
    if section == DraftSection.FORM and form_depth(launch=launch) == FormDepth.DEEP:
        schema = DeepFormSection
    purpose = PURPOSES.get(section, LLMPurpose.ONBOARDING)
    try:
        result = _ask(
            db, launch=launch, business=business, section=section, schema=schema
        )
    except LLMError as exc:
        logger.warning("regeneration_failed", extra={"prompt": prompt_name})
        return _fail(db, launch, code=failure_code(exc), section=section, exc=exc)
    try:
        record_llm_result(
            db,
            owner=launch.owner,
            purpose=purpose,
            result=result,
            related_type=RELATED_TYPE,
            related_id=launch.id,
        )
        db.commit()
        answer = result.value
        problems: list[list[dict[str, str]]] = []
        if section == DraftSection.CREATIVE:
            reviewed = review_copy(
                db, launch=launch, business=business, creatives=list(answer.creatives)
            )
            answer = CreativeSection(creatives=reviewed.creatives)
            problems = reviewed.problems
        _store(
            db,
            launch=launch,
            business=business,
            section=section,
            answer=answer,
            problems=problems,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "regeneration_store_failed",
            extra={"launch": str(launch.id), "section": section},
        )
        return _fail(db, launch, code="unknown")
    return "ready"


def _ask(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    section: str,
    schema: type[BaseModel],
) -> Any:
    from app.modules.ads.services.proposal import (
        every_picture_written,
        prompt_variables,
    )

    prompt_name, _schema, previous_key = SECTIONS[section]
    template, version = prompts().get(prompt_name)
    variables = prompt_variables(db, launch=launch, business=business)
    variables[previous_key] = _readable(draft_field.chosen(launch.draft, section))
    variables["unknown_names"] = _unknown_names(launch=launch)
    if section == DraftSection.FORM:
        variables.update(
            form_variables(db, launch=launch, depth=form_depth(launch=launch))
        )
    ask = {
        "prompt": render(template, variables),
        "schema": schema,
        "prompt_name": prompt_name,
        "prompt_version": version,
    }
    with claude(timeout=WRITING_TIMEOUT_SECONDS) as client:
        if section == DraftSection.CREATIVE:
            return every_picture_written(db, client, launch=launch, ask=ask)
        return client.structured(**ask)


def _store(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    section: str,
    answer: BaseModel,
    problems: list[list[dict[str, str]]],
) -> None:
    """Replace the section, spend its one attempt, rebuild the spec."""
    from app.modules.ads.services.interests import (
        request_confirmation,
        request_estimate,
    )
    from app.modules.ads.services.targeting import rebuild_targeting, remember_terms
    from app.modules.ads.services.variants import reseed_words

    payload = answer.model_dump()
    value = _section_value(section, payload, limit=question_limit(launch=launch))
    draft = fresh(launch, "draft")
    before = draft_field.chosen(draft, section)
    draft_field.propose(draft, section, value)
    draft_field.mark_regenerated(draft, section)
    if section == DraftSection.CREATIVE:
        draft_field.set_copy_review(draft, problems)
    if section == DraftSection.INTERESTS:
        draft_field.choose(draft, section, draft_field.ai_picks(value))
        draft_field.set_unconfirmed(draft, section, [])
    if section == DraftSection.FORM:
        draft_field.choose(draft, section, value)
    if section == DraftSection.AUDIENCE:
        draft_field.choose(draft, section, {**value, **_kept(before)})
    rebuild_targeting(db, launch=launch, business=business)
    launch.status = str(LaunchStatus.READY)
    launch.step = str(LaunchStep.VALIDATE)
    launch.progress = 100
    launch.finished_at = utcnow()
    db.flush()
    if section == DraftSection.INTERESTS:
        remember_terms(
            db,
            launch=launch,
            items=draft_field.chosen(launch.draft, section),
            source=InterestSource.AI,
        )
        request_confirmation(db, launch)
    elif section == DraftSection.AUDIENCE:
        request_estimate(db, launch)
    if section == DraftSection.CREATIVE:
        reseed_words(db, launch=launch)
    db.commit()


def _kept(before: Any) -> dict[str, Any]:
    if not isinstance(before, dict):
        return {}
    return {key: before[key] for key in KEPT_ON_REGENERATE if key in before}


def _section_value(section: str, payload: dict[str, Any], *, limit: int) -> Any:
    if section == DraftSection.INTERESTS:
        return payload["interests"]
    if section == DraftSection.FORM:
        return draft_field.model_questions(payload["form_questions"], limit=limit)
    if section == DraftSection.CREATIVE:
        return payload["creatives"]
    return payload


def _unknown_names(*, launch: CampaignLaunch) -> str:
    rows = draft_field.unconfirmed(launch.draft, DraftSection.INTERESTS)
    names = [
        str(row.get("query", "")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("query", "")).strip()
    ]
    if not names:
        return "None - every name on the previous list was found."
    return ", ".join(names)


def _readable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def failure_code(exc: LLMError) -> str:
    if isinstance(exc, ClaudeRateLimited):
        return "rate_limited"
    if isinstance(exc, StructuredOutputError):
        return "schema_error"
    if isinstance(exc, ClaudeTemporaryError):
        return "temporary"
    return "unavailable"


def _fail(
    db: Session,
    launch: CampaignLaunch,
    *,
    code: str,
    section: str = "",
    exc: LLMError | None = None,
) -> str:
    """A failed regeneration leaves the previous answer intact."""
    from app.modules.audit.services import record_llm_error

    if exc is not None and section in SECTIONS:
        prompt_name = SECTIONS[section][0]
        record_llm_error(
            db,
            owner=launch.owner,
            purpose=PURPOSES.get(section, LLMPurpose.ONBOARDING),
            exc=exc,
            prompt_name=prompt_name,
            prompt_version=prompts().latest(prompt_name),
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            related_type=RELATED_TYPE,
            related_id=launch.id,
        )
    launch.status = str(LaunchStatus.READY)
    launch.progress = 100
    launch.error_code = code
    db.commit()
    return code


# -- the answers a question offers ---------------------------------------------------


def request_options(db: Session, *, launch: CampaignLaunch, kinds: list[str]) -> None:
    """Ask for options for the questions that have just been written."""
    from app.modules.ads.tasks import suggest_options_task

    if not kinds:
        return
    launch_id = str(launch.id)
    for kind in kinds:
        on_commit(db, lambda kind=kind: suggest_options_task.delay(launch_id, kind))


def suggest_options(db: Session, *, launch_id: UUID | str, kind: str) -> str:
    """The worker half. Returns a word for the task log."""
    from app.modules.audit.services import record_llm_result
    from app.modules.billing.services import require_preparation

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    business = _business(db, launch)
    if business is None:
        return _settle(db, launch, kind)
    question = _question(launch, kind)
    if question is None:
        return "gone"
    try:
        require_preparation(db, owner=launch.owner)
        result = _ask_options(
            db, launch=launch, business=business, label=str(question["label"])
        )
    except NoEntitlement:
        return _settle(db, launch, kind)
    except LLMError as exc:
        _record_options_failure(db, launch, exc)
        return _settle(db, launch, kind)
    except Exception:
        logger.exception("options_failed", extra={"launch": str(launch.id)})
        return _settle(db, launch, kind)
    try:
        record_llm_result(
            db,
            owner=launch.owner,
            purpose=LLMPurpose.FORM_BUILD,
            result=result,
            related_type=LAUNCH_RELATED_TYPE,
            related_id=launch.id,
        )
        _store_options(db, launch, kind, [str(item) for item in result.value.options])
    except Exception:
        db.rollback()
        logger.exception("options_store_failed", extra={"launch": str(launch.id)})
        return _settle(db, launch, kind)
    return str(len(result.value.options))


def _ask_options(
    db: Session, *, launch: CampaignLaunch, business: Business, label: str
) -> Any:
    from app.modules.ads.services.proposal import prompt_variables

    template, version = prompts().get(OPTIONS_PROMPT)
    variables = prompt_variables(db, launch=launch, business=business)
    variables["question"] = label
    with claude() as client:
        return client.structured(
            prompt=render(template, variables),
            schema=QuestionOptions,
            prompt_name=OPTIONS_PROMPT,
            prompt_version=version,
        )


def _record_options_failure(db: Session, launch: CampaignLaunch, exc: LLMError) -> None:
    from app.modules.audit.services import record_llm_error

    record_llm_error(
        db,
        owner=launch.owner,
        purpose=LLMPurpose.FORM_BUILD,
        exc=exc,
        prompt_name=OPTIONS_PROMPT,
        prompt_version=prompts().latest(OPTIONS_PROMPT),
        model=model_for(ASKED),
        currency=str(settings.anthropic_price_currency),
        related_type=LAUNCH_RELATED_TYPE,
        related_id=launch.id,
    )
    db.commit()


def _question(launch: CampaignLaunch, kind: str) -> dict[str, Any] | None:
    for item in draft_field.chosen(launch.draft, DraftSection.FORM) or []:
        if isinstance(item, dict) and str(item.get("kind", "")) == kind:
            return item
    return None


def _store_options(
    db: Session, launch: CampaignLaunch, kind: str, options: list[str]
) -> None:
    row = db.scalar(
        select(CampaignLaunch)
        .where(CampaignLaunch.id == launch.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        db.rollback()
        return
    draft = fresh(row, "draft")
    chosen = draft_field.chosen(draft, DraftSection.FORM) or []
    for item in chosen:
        if isinstance(item, dict) and str(item.get("kind", "")) == kind:
            item["options"] = options
            item.pop(PENDING, None)
    draft_field.choose(draft, DraftSection.FORM, chosen)
    db.commit()


def _settle(db: Session, launch: CampaignLaunch, kind: str) -> str:
    _store_options(db, launch, kind, [])
    return "none"
