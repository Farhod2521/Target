"""Which form this launch hangs on its ads, how it ends, and its questions at two
depths - written by a worker, and switched between on the owner's press."""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from llmkit import LLMError, render
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import on_commit
from app.common.llm import ASKED, claude, model_for, prompts
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    FORM_DEPTH,
    FORM_DEPTH_LIMITS,
    FORM_DEPTH_WANTED,
    HIGHER_INTENT,
    LAUNCH_RELATED_TYPE,
    LEAD_FORM_CHOICE,
    LEAD_FORM_ENDING,
    LEAD_FORM_NAME,
    LEAD_FORM_NAME_MAX,
    LEAD_FORM_QUESTIONS,
    MAX_OPTIONS,
    QUESTION_TYPES,
    WRITING_TIMEOUT_SECONDS,
    DraftSection,
    FormDepth,
    LaunchStatus,
    LaunchStep,
)
from app.modules.ads.exceptions import (
    DeliveryOptionLocked,
    DeliveryOptionUnusable,
    DraftNotReady,
    FormVariantNotReady,
    UnknownLeadForm,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.lead_form import (
    PENDING_MINUTES,
    ai_ending,
    depth_changeable,
    form_depth,
    form_variables,
    offers_form_depth,
    variant_pending,
)
from app.modules.ads.services.sections import failure_code
from app.modules.audit.constants import LLMPurpose
from app.modules.billing.exceptions import NoEntitlement
from app.modules.businesses.models import Business
from core.agent import DeepFormSection, FormSection
from core.leads.ending import FormEnding

logger = logging.getLogger(__name__)
PROMPT = "form_rewrite"


def _locked(db: Session, launch_id: Any) -> CampaignLaunch | None:
    return db.scalar(
        select(CampaignLaunch)
        .where(CampaignLaunch.id == launch_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _orphan_kept_form(launch: CampaignLaunch) -> None:
    """Forget the form an earlier attempt built."""
    fresh(launch, "created_refs").pop(LaunchStep.FORM, None)


# -- the choice ------------------------------------------------------------------------


def choose_lead_form(
    db: Session,
    *,
    launch: CampaignLaunch,
    external_id: str,
    questions: list[dict[str, Any]] | None = None,
    name: str = "",
    ending: FormEnding | None = None,
) -> None:
    """Point this launch at an existing form, or back at a new one. Caller commits."""
    picked = _verified(db, launch=launch, external_id=external_id)
    before = (launch.answers or {}).get(LEAD_FORM_ENDING)
    launch.lead_form_external_id = picked
    launch.answers = _answered(
        launch.answers or {},
        picked=picked,
        questions=questions,
        name=name,
        ending=ending,
    )
    if not picked and launch.answers.get(LEAD_FORM_ENDING) != before:
        _orphan_kept_form(launch)
    if launch.draft:
        draft_field.set_source(
            fresh(launch, "draft"), draft_field.LEAD_FORM, draft_field.BY_OWNER
        )
    db.flush()


def let_ai_choose(
    db: Session, *, launch: CampaignLaunch, depth: str = "", now: datetime | None = None
) -> None:
    """Hand the question back to the rules, as it was before anybody answered."""
    answers = launch.answers or {}
    had_ending = LEAD_FORM_ENDING in answers
    launch.answers = {
        key: value
        for key, value in answers.items()
        if key
        not in (
            LEAD_FORM_CHOICE,
            LEAD_FORM_QUESTIONS,
            LEAD_FORM_NAME,
            LEAD_FORM_ENDING,
            FORM_DEPTH_WANTED,
        )
    }
    launch.lead_form_external_id = ""
    if had_ending:
        _orphan_kept_form(launch)
    if launch.draft:
        draft_field.clear_source(fresh(launch, "draft"), draft_field.LEAD_FORM)
    db.flush()
    if depth in FormDepth.values:
        _choose_depth(db, launch=launch, depth=depth, now=now)


def _choose_depth(
    db: Session, *, launch: CampaignLaunch, depth: str, now: datetime | None
) -> None:
    if draft_field.is_written(launch.draft) and depth != form_depth(launch=launch):
        if not depth_changeable(db, launch=launch):
            return
        try:
            apply_form_depth(db, launch=launch, depth=depth)
        except FormVariantNotReady:
            if now is not None:
                request_form_variant(db, launch=launch, depth=depth, now=now)
                launch.answers = {**launch.answers, FORM_DEPTH_WANTED: depth}
                db.flush()
            return
    launch.answers = {
        **launch.answers,
        FORM_DEPTH: depth,
        HIGHER_INTENT: depth == FormDepth.DEEP,
    }
    db.flush()


def choose_form_ending(
    db: Session, *, launch: CampaignLaunch, business: Business, ending: FormEnding
) -> None:
    """The screen after a new form, as the owner left it on the proposal."""
    stored = (launch.answers or {}).get(LEAD_FORM_ENDING)
    if stored is None and ending == ai_ending(business=business):
        return
    if stored == ending.as_answer():
        return
    launch.answers = {**(launch.answers or {}), LEAD_FORM_ENDING: ending.as_answer()}
    _orphan_kept_form(launch)
    db.flush()


def _answered(
    answers: dict[str, Any],
    *,
    picked: str,
    questions: list[dict[str, Any]] | None,
    name: str,
    ending: FormEnding | None,
) -> dict[str, Any]:
    answered = dict(answers)
    answered[LEAD_FORM_CHOICE] = draft_field.BY_OWNER
    answered.pop(FORM_DEPTH_WANTED, None)
    if picked:
        answered.pop(LEAD_FORM_QUESTIONS, None)
        answered.pop(LEAD_FORM_NAME, None)
        answered.pop(LEAD_FORM_ENDING, None)
        return answered
    if questions is not None:
        answered[LEAD_FORM_QUESTIONS] = _normalised(questions)
    if name.strip():
        answered[LEAD_FORM_NAME] = name.strip()[:LEAD_FORM_NAME_MAX]
    if ending is not None:
        answered[LEAD_FORM_ENDING] = ending.as_answer()
    return answered


def _normalised(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in questions:
        kind = str(item.get("kind", "")).strip()
        label = str(item.get("label", "")).strip()
        if not kind:
            continue
        question: dict[str, Any] = {"kind": kind, "label": label}
        if kind not in QUESTION_TYPES:
            question["options"] = [
                str(option).strip()
                for option in item.get("options") or ()
                if str(option).strip()
            ][:MAX_OPTIONS]
        kept.append(question)
    return kept


def _verified(db: Session, *, launch: CampaignLaunch, external_id: str) -> str:
    from app.modules.ads.services.access import launch_page_for
    from app.modules.leads.selectors.reads import collecting_form

    picked = external_id.strip()
    if not picked:
        return ""
    page = launch_page_for(db, launch=launch)
    form = collecting_form(db, owner=launch.owner, page=page, external_id=picked)
    if form is None:
        raise UnknownLeadForm
    return form.external_id


# -- the depth -------------------------------------------------------------------------


def _check(db: Session, *, launch: CampaignLaunch, depth: str) -> None:
    if depth not in FormDepth.values:
        raise DeliveryOptionUnusable
    if campaign_type_locked(launch=launch):
        raise DeliveryOptionLocked
    if not offers_form_depth(db, launch=launch):
        raise DeliveryOptionUnusable
    if not launch.draft:
        raise DraftNotReady


def request_form_variant(
    db: Session, *, launch: CampaignLaunch, depth: str, now: datetime
) -> None:
    """Have this depth's questions written, unless they are or are being."""
    from app.modules.ads.tasks import rewrite_form_task
    from app.modules.billing.services import require_preparation

    _check(db, launch=launch, depth=depth)
    if depth == form_depth(launch=launch):
        return
    kept = draft_field.form_variants(launch.draft).get(depth) or {}
    if "questions" in kept or variant_pending(kept, now=now, minutes=PENDING_MINUTES):
        return
    require_preparation(db, owner=launch.owner)
    draft_field.keep_form_variant(
        fresh(launch, "draft"), depth, {"pending_at": now.isoformat()}
    )
    db.flush()
    launch_id = str(launch.id)
    on_commit(db, lambda: rewrite_form_task.delay(launch_id, depth))


def apply_form_depth(db: Session, *, launch: CampaignLaunch, depth: str) -> None:
    """Make the kept questions of ``depth`` the form, keeping the current ones."""
    _check(db, launch=launch, depth=depth)
    current = form_depth(launch=launch)
    if depth == current:
        return
    kept = draft_field.form_variants(launch.draft).get(depth) or {}
    if "questions" not in kept:
        raise FormVariantNotReady
    draft = fresh(launch, "draft")
    draft_field.keep_form_variant(
        draft,
        current,
        {
            "questions": draft_field.chosen(draft, DraftSection.FORM) or [],
            "lead_form": launch.lead_form_external_id,
        },
    )
    questions = list(kept["questions"])
    draft_field.propose(draft, DraftSection.FORM, questions)
    draft_field.choose(draft, DraftSection.FORM, questions)
    answers = {**(launch.answers or {}), FORM_DEPTH: depth}
    answers.pop(FORM_DEPTH_WANTED, None)
    if answers.get(LEAD_FORM_QUESTIONS):
        answers[LEAD_FORM_QUESTIONS] = questions
    launch.answers = answers
    _orphan_kept_form(launch)
    db.flush()


def rewrite_form(db: Session, *, launch_id: UUID | str, depth: str) -> str:
    """The worker half. Returns a word for the task log."""
    from app.modules.audit.services import record_llm_result
    from app.modules.billing.services import require_preparation
    from app.modules.businesses.selectors import business_for_page

    if depth not in FormDepth.values:
        return "unknown depth"
    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    if launch.status != LaunchStatus.READY:
        return _keep(
            db, launch_id=launch.id, depth=depth, value={"failed": "not_ready"}
        )
    try:
        require_preparation(db, owner=launch.owner)
    except NoEntitlement:
        return _keep(
            db,
            launch_id=launch.id,
            depth=depth,
            value={"failed": "subscription_expired"},
        )
    business = business_for_page(db, owner=launch.owner, page=launch.page)
    if business is None:
        return _keep(
            db, launch_id=launch.id, depth=depth, value={"failed": "profile_incomplete"}
        )
    try:
        result = _ask(db, launch=launch, business=business, depth=depth)
    except LLMError as exc:
        logger.warning("form_rewrite_failed", extra={"launch": str(launch.id)})
        _record_failure(db, launch=launch, exc=exc)
        return _keep(
            db, launch_id=launch.id, depth=depth, value={"failed": failure_code(exc)}
        )
    record_llm_result(
        db,
        owner=launch.owner,
        purpose=LLMPurpose.FORM_BUILD,
        result=result,
        related_type=LAUNCH_RELATED_TYPE,
        related_id=launch.id,
    )
    questions = draft_field.model_questions(
        result.value.model_dump()["form_questions"], limit=FORM_DEPTH_LIMITS[depth]
    )
    word = _keep(
        db,
        launch_id=launch.id,
        depth=depth,
        value={"questions": questions, "lead_form": ""},
        word="ready",
    )
    return (
        _apply_wanted(db, launch_id=launch.id, depth=depth) if word == "ready" else word
    )


def _apply_wanted(db: Session, *, launch_id: UUID, depth: str) -> str:
    row = _locked(db, launch_id)
    if (
        row is None
        or (row.answers or {}).get(FORM_DEPTH_WANTED) != depth
        or row.lead_form_external_id
        or not depth_changeable(db, launch=row)
    ):
        db.rollback()
        return "ready"
    row.answers = {**row.answers, HIGHER_INTENT: depth == FormDepth.DEEP}
    apply_form_depth(db, launch=row, depth=depth)
    db.commit()
    return "applied"


def _ask(db: Session, *, launch: CampaignLaunch, business: Business, depth: str) -> Any:
    from app.modules.ads.services.proposal import prompt_variables

    template, version = prompts().get(PROMPT)
    variables: dict[str, object] = {
        **prompt_variables(db, launch=launch, business=business),
        **form_variables(db, launch=launch, depth=depth),
    }
    schema = DeepFormSection if depth == FormDepth.DEEP else FormSection
    with claude(timeout=WRITING_TIMEOUT_SECONDS) as client:
        return client.structured(
            prompt=render(template, variables),
            schema=schema,
            prompt_name=PROMPT,
            prompt_version=version,
        )


def _keep(
    db: Session, *, launch_id: UUID, depth: str, value: dict[str, Any], word: str = ""
) -> str:
    row = _locked(db, launch_id)
    if row is None or not row.draft:
        db.rollback()
        return "gone"
    draft_field.keep_form_variant(fresh(row, "draft"), depth, value)
    db.commit()
    return word or str(value.get("failed", ""))


def _record_failure(db: Session, *, launch: CampaignLaunch, exc: LLMError) -> None:
    from app.modules.audit.services import record_llm_error

    record_llm_error(
        db,
        owner=launch.owner,
        purpose=LLMPurpose.FORM_BUILD,
        exc=exc,
        prompt_name=PROMPT,
        prompt_version=prompts().latest(PROMPT),
        model=model_for(ASKED),
        currency=str(settings.anthropic_price_currency),
        related_type=LAUNCH_RELATED_TYPE,
        related_id=launch.id,
    )
    db.commit()
