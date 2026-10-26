"""Ask Claude for a proposal, have it read its own copy once more, and store it."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from llmkit import (
    ClaudeAuthError,
    ClaudeRateLimited,
    ClaudeRefused,
    ClaudeTemporaryError,
    LLMError,
    LLMResult,
    Spend,
    StructuredOutputError,
    halves,
    render,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.common.llm import ASKED, both, claude, model_for, prompts
from app.common.money import format_minor, provider_money
from app.common.presets import goals_for, seeds_for, traits_for
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    BUILD_PROGRESS,
    LAUNCH_DRAFT_PROMPT,
    LAUNCH_RELATED_TYPE,
    PROMPT_LANGUAGE,
    WRITING_TIMEOUT_SECONDS,
    DraftSection,
    FormDepth,
    InterestSource,
    LaunchStatus,
    LaunchStep,
    TextMode,
)
from app.modules.ads.exceptions import FreeProposalsUsed
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.audiences_chosen import KnownTerm, confirmed_terms
from app.modules.ads.selectors.copy_notes import (
    AdvertFacts,
    button_action,
    facts_by_advert,
    offer_text,
)
from app.modules.ads.selectors.goals import goal_preset
from app.modules.ads.selectors.lead_form import (
    form_depth,
    form_rule_for,
    question_limit,
)
from app.modules.ads.selectors.variants import variants_needing_words
from app.modules.audit.constants import LLMCallStatus, LLMPurpose
from app.modules.billing.exceptions import NoEntitlement
from app.modules.businesses.models import Business
from core.agent import (
    CreativeProposal,
    LaunchDraft,
    LaunchDraftDeepForm,
    LaunchDraftWithoutForm,
)
from core.agent.copy_check import AdWords, CopyFinding, check_against_offer
from core.agent.copy_review import CopyReview

logger = logging.getLogger(__name__)
PROMPT = LAUNCH_DRAFT_PROMPT
REVIEW_PROMPT = "copy_review"
RELATED_TYPE = LAUNCH_RELATED_TYPE
TURN: Final = "Write the proposal for the account described above."


def _business(db: Session, launch: CampaignLaunch) -> Business | None:
    from app.modules.businesses.selectors import business_for_page

    return business_for_page(db, owner=launch.owner, page=launch.page)


def build_draft(db: Session, *, launch_id: UUID | str, run: str = "") -> str:
    """One preparation, start to finish. Returns a word for the task log."""
    from app.modules.ads.services.launch import check_preparation_allowance
    from app.modules.audit.services import record_llm_result

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    if not _is_this_run(db, launch, run=run):
        db.rollback()
        return "superseded"
    db.commit()
    try:
        check_preparation_allowance(db, owner=launch.owner)
    except NoEntitlement:
        return _fail(db, launch, run=run, code="subscription_expired")
    except FreeProposalsUsed:
        return _fail(db, launch, run=run, code="free_proposals_used")
    business = _business(db, launch)
    if business is None or not business.category:
        return _fail(db, launch, run=run, code="profile_incomplete")
    _advance(db, launch, step=LaunchStep.ASKING)
    asked_for = str(launch.answers.get("goal", ""))
    asked_offer = str(launch.answers.get("offer_text", ""))
    try:
        result = _ask(db, launch=launch, business=business)
    except ClaudeRateLimited:
        return _fail(
            db, launch, run=run, code="rate_limited", call=LLMCallStatus.RATE_LIMITED
        )
    except StructuredOutputError as exc:
        logger.warning(
            "launch_draft_refused",
            extra={"launch": str(launch.id), "problem": str(exc)},
        )
        return _fail(
            db,
            launch,
            run=run,
            code="schema_error",
            call=LLMCallStatus.SCHEMA_ERROR,
            attempts=exc.attempts or 1,
            spent=exc.spent,
        )
    except ClaudeTemporaryError:
        return _fail(db, launch, run=run, code="temporary", call=LLMCallStatus.FAILED)
    except ClaudeAuthError:
        logger.error("claude_auth_failed", extra={"launch_id": str(launch.id)})
        return _fail(db, launch, run=run, code="unavailable", call=LLMCallStatus.FAILED)
    except ClaudeRefused as exc:
        logger.warning("launch_draft_declined", extra={"launch": str(launch.id)})
        return _fail(
            db,
            launch,
            run=run,
            code="unavailable",
            call=LLMCallStatus.FAILED,
            attempts=exc.attempts or 1,
            spent=exc.spent,
        )
    except LLMError:
        return _fail(db, launch, run=run, code="unavailable", call=LLMCallStatus.FAILED)
    _advance(db, launch, step=LaunchStep.LLM)
    try:
        record_llm_result(
            db,
            owner=launch.owner,
            purpose=LLMPurpose.ONBOARDING,
            result=result,
            related_type=RELATED_TYPE,
            related_id=launch.id,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("llm_call_not_recorded", extra={"launch": str(launch.id)})
    try:
        if not _still_wanted(db, launch, goal=asked_for, offer=asked_offer):
            return _abandon(db, launch, run=run)
        reviewed = review_copy(
            db, launch=launch, business=business, creatives=list(result.value.creatives)
        )
        proposal = result.value.model_copy(update={"creatives": reviewed.creatives})
        if not _store(
            db,
            launch=launch,
            business=business,
            proposal=proposal,
            problems=reviewed.problems,
            run=run,
        ):
            return "superseded"
    except Exception:
        db.rollback()
        logger.exception("build_draft_store_failed", extra={"launch": str(launch.id)})
        return _fail(db, launch, run=run, code="unknown")
    return "ready"


def _ask(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> LLMResult[LaunchDraft]:
    """The one call. Every section at once, on purpose."""
    template, version = prompts().get(PROMPT)
    instructions, account = halves(template)
    text = render(account, prompt_variables(db, launch=launch, business=business))
    schema = _schema(db, launch=launch)
    with claude(timeout=WRITING_TIMEOUT_SECONDS) as client:
        return every_picture_written(
            db,
            client,
            launch=launch,
            ask={
                "prompt": TURN,
                "system": instructions,
                "system_tail": text,
                "schema": schema,
                "prompt_name": PROMPT,
                "prompt_version": version,
            },
        )


def every_picture_written(
    db: Session, client: Any, *, launch: CampaignLaunch, ask: Mapping[str, Any]
) -> LLMResult[Any]:
    """An answer with words for every picture that needs them, asked twice at most."""
    wanted = len(variants_needing_words(db, launch=launch))
    first = client.structured(**ask)
    if len(first.value.creatives) >= wanted:
        return first  # type: ignore[no-any-return]
    second = client.structured(**ask)
    paid = both(first, second)
    if len(second.value.creatives) >= len(first.value.creatives):
        return paid
    return replace(paid, value=first.value)


def prompt_variables(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> dict[str, str]:
    """Everything the prompt is allowed to know."""
    from app.modules.businesses.selectors import category_label

    goal = str(launch.answers.get("goal", ""))
    label = next(
        (
            preset.label
            for preset in goals_for(
                provider=launch.provider, category=business.category
            )
            if preset.goal == goal
        ),
        goal,
    )
    seeds = seeds_for(provider=launch.provider, category=business.category)
    return {
        "business_name": business.name,
        "business_category": category_label(business),
        "city": business.city or "—",
        "country_code": business.country_code,
        "owner_language": PROMPT_LANGUAGE.get(
            launch.owner.language, PROMPT_LANGUAGE["uz"]
        ),
        "offer_text": offer_text(db, launch=launch, business=business),
        "goal_label": str(label),
        "goal_text": str(launch.answers.get("goal_text") or "").strip() or "—",
        "button_action": button_action(db, launch=launch),
        "daily_budget": format_minor(
            amount_minor=launch.daily_budget_minor,
            currency=launch.currency,
            places=provider_money(provider=launch.provider).decimal_places(
                launch.currency
            ),
        ),
        "currency": launch.currency,
        "seed_interests": "\n".join(f"- {seed.label} ({seed.query})" for seed in seeds),
        "known_interests": _known_interests(db, launch=launch),
        "form_rule": _form_rule(db, launch=launch),
        "trait_options": _trait_options(launch=launch, business=business),
        **ad_copy_variables(db, launch=launch),
    }


def _asks_for_a_form(db: Session, *, launch: CampaignLaunch) -> bool:
    preset = goal_preset(db, launch=launch)
    return preset is not None and preset.needs_lead_form


def _schema(db: Session, *, launch: CampaignLaunch) -> type[LaunchDraft]:
    if not _asks_for_a_form(db, launch=launch):
        return LaunchDraftWithoutForm
    if form_depth(launch=launch) == FormDepth.DEEP:
        return LaunchDraftDeepForm
    return LaunchDraft


def _form_rule(db: Session, *, launch: CampaignLaunch) -> str:
    if _asks_for_a_form(db, launch=launch):
        return form_rule_for(depth=form_depth(launch=launch))
    return (
        "This advert has no form - its button does something else - so return "
        "`form_questions` as an empty list."
    )


def _known_interests(db: Session, *, launch: CampaignLaunch) -> str:
    rows = confirmed_terms(db, owner=launch.owner, provider=launch.provider)
    if not rows:
        return (
            "None yet. No campaign of this advertiser's has run on a name Meta "
            "confirmed, so choose from the catalogue above and from the offer."
        )
    return "\n".join(f"- {_known_line(row)}" for row in rows)


def _trait_options(*, launch: CampaignLaunch, business: Business) -> str:
    traits = traits_for(provider=launch.provider, category=business.category)
    if not traits:
        return "None for this category - return `traits` as an empty list."
    return "\n".join(f"- {trait.query} ({trait.label})" for trait in traits)


def _known_line(row: KnownTerm) -> str:
    if row.audience_size is None:
        return f"{row.label} ({row.query})"
    return f"{row.label} ({row.query}) - {row.audience_size:,} people"


def ad_copy_variables(db: Session, *, launch: CampaignLaunch) -> dict[str, str]:
    """How many adverts the model writes, and what each one is about."""
    rows = variants_needing_words(db, launch=launch)
    if not rows:
        return {
            "creative_count": "0",
            "ad_briefs": (
                "None. Every picture is an Instagram post, or none is chosen yet - "
                "write no adverts."
            ),
        }
    if launch.answers.get("text_mode") == TextMode.EACH:
        briefs = "\n".join(
            f"{index}. {row.brief.strip() or '-'}"
            for index, row in enumerate(rows, start=1)
        )
    else:
        briefs = (
            f"{len(rows)} picture(s), all about the offer above - the owner wrote one "
            "text for every advert."
        )
    return {"creative_count": str(len(rows)), "ad_briefs": briefs}


def _store(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    proposal: LaunchDraft,
    problems: list[list[dict[str, str]]],
    run: str,
) -> bool:
    """Three sections, a pre-selection, and a rebuilt spec, in one write."""
    from app.modules.ads.services.interests import request_confirmation
    from app.modules.ads.services.locations import request_locations
    from app.modules.ads.services.targeting import (
        apply_campaign_type,
        apply_conversion_event,
        apply_lead_form,
        apply_placement,
        apply_url_tags,
        rebuild_targeting,
        remember_terms,
        suggested_geo,
    )
    from app.modules.ads.services.variants import seed_words

    if not _is_this_run(db, launch, run=run):
        db.rollback()
        return False
    draft = draft_field.empty_draft()
    audience = proposal.audience.model_dump()
    draft_field.propose(draft, "audience", audience)
    draft_field.propose(
        draft, "interests", [item.model_dump() for item in proposal.interests]
    )
    draft_field.propose(
        draft, DraftSection.CREATIVE, [item.model_dump() for item in proposal.creatives]
    )
    draft_field.set_copy_review(draft, problems)
    questions = draft_field.model_questions(
        [item.model_dump() for item in proposal.form_questions],
        limit=question_limit(launch=launch),
    )
    draft_field.propose(draft, "form", questions)
    picked = draft_field.ai_picks([item.model_dump() for item in proposal.interests])
    draft_field.choose(draft, "interests", picked)
    draft_field.choose(draft, DraftSection.FORM, questions)
    traits = [
        {"label": trait.label, "query": trait.query, "kind": trait.kind}
        for trait in traits_for(provider=launch.provider, category=business.category)
    ]
    named = {name.strip().casefold() for name in proposal.traits}
    draft_field.propose(draft, DraftSection.TRAITS, traits)
    draft_field.choose(
        draft,
        DraftSection.TRAITS,
        [
            {**item, "external_id": ""}
            for item in traits
            if item["query"].casefold() in named
        ],
    )
    draft_field.choose(
        draft,
        "audience",
        {
            **audience,
            geo_field.GEO_KEY: geo_field.from_choice(
                suggested_geo(
                    db,
                    owner=launch.owner,
                    business=business,
                    page=launch.page,
                    radius_km=audience.get("radius_km"),
                )
            ),
        },
    )
    launch.draft = draft
    apply_placement(db, launch=launch)
    apply_lead_form(db, launch=launch)
    apply_campaign_type(db, launch=launch)
    apply_conversion_event(db, launch=launch)
    apply_url_tags(db, launch=launch)
    rebuild_targeting(db, launch=launch, business=business)
    launch.status = str(LaunchStatus.READY)
    launch.step = str(LaunchStep.VALIDATE)
    launch.progress = 100
    launch.finished_at = utcnow()
    db.flush()
    remember_terms(db, launch=launch, items=picked, source=InterestSource.AI)
    seed_words(db, launch=launch)
    request_confirmation(db, launch)
    if geo_field.unchecked_cities(draft_field.chosen(launch.draft, "audience")):
        request_locations(db, launch)
    db.commit()
    return True


def _abandon(db: Session, launch: CampaignLaunch, *, run: str) -> str:
    if not _is_this_run(db, launch, run=run):
        db.rollback()
        return "superseded"
    launch.status = str(LaunchStatus.DRAFT)
    launch.progress = 0
    launch.finished_at = utcnow()
    db.commit()
    logger.info("launch_preparation_abandoned", extra={"launch": str(launch.id)})
    return "goal_changed"


def _still_wanted(
    db: Session, launch: CampaignLaunch, *, goal: str, offer: str
) -> bool:
    db.refresh(launch, attribute_names=["answers"])
    answers = launch.answers or {}
    return (
        str(answers.get("goal", "")) == goal
        and str(answers.get("offer_text", "")) == offer
    )


def _advance(db: Session, launch: CampaignLaunch, *, step: str) -> None:
    launch.step = step
    launch.progress = BUILD_PROGRESS[step][0]
    db.commit()


def _fail(
    db: Session,
    launch: CampaignLaunch,
    *,
    run: str,
    code: str,
    call: LLMCallStatus | None = None,
    attempts: int = 1,
    spent: Spend | None = None,
) -> str:
    """Record the failure on the row and, when Claude answered, in the audit."""
    from app.modules.audit.services import record_llm_failure

    if call is not None:
        record_llm_failure(
            db,
            owner=launch.owner,
            purpose=LLMPurpose.ONBOARDING,
            status=call,
            prompt_name=PROMPT,
            prompt_version=prompts().latest(PROMPT),
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            attempts=attempts,
            spent=spent,
            related_type=RELATED_TYPE,
            related_id=launch.id,
        )
        db.commit()
    if not _is_this_run(db, launch, run=run):
        db.rollback()
        return "superseded"
    launch.status = str(LaunchStatus.FAILED)
    launch.progress = 0
    launch.error_code = code
    launch.finished_at = utcnow()
    db.commit()
    logger.warning(
        "launch_preparation_failed",
        extra={"launch": str(launch.id), "owner": str(launch.owner_id), "code": code},
    )
    return code


def _is_this_run(db: Session, launch: CampaignLaunch, *, run: str) -> bool:
    """Whether the row still carries this task's run. Locks it."""
    if not run:
        return True
    started = db.scalar(
        select(CampaignLaunch.started_at)
        .where(CampaignLaunch.id == launch.id)
        .with_for_update()
    )
    return started == datetime.fromisoformat(run)


# -- the second read of the copy -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReviewedCopy:
    creatives: list[CreativeProposal]
    problems: list[list[dict[str, str]]] = field(default_factory=list)


def review_copy(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    creatives: list[CreativeProposal],
) -> ReviewedCopy:
    """The proposed adverts, fixed where a second read found them wrong."""
    if not creatives:
        return ReviewedCopy(creatives=creatives)
    facts = _facts_for(db, launch=launch, business=business, count=len(creatives))
    sends_to = button_action(db, launch=launch)
    findings = [
        check_against_offer(words=_words(item), facts=row.joined, sends_to=sends_to)
        for item, row in zip(creatives, facts, strict=True)
    ]
    try:
        result = _ask_review(
            business=business,
            creatives=creatives,
            findings=findings,
            facts=facts,
            sends_to=sends_to,
        )
    except LLMError as exc:
        _record_review_failure(db, launch, exc)
        return ReviewedCopy(creatives=creatives)
    _record_review(db, launch, result)
    return _apply_review(launch, creatives=creatives, review=result.value)


def _facts_for(
    db: Session, *, launch: CampaignLaunch, business: Business, count: int
) -> list[AdvertFacts]:
    rows = facts_by_advert(db, launch=launch, business=business)
    if len(rows) == count:
        return rows
    shared = AdvertFacts(offer=rows[0].offer if rows else "")
    return [shared] * count


def _ask_review(
    *,
    business: Business,
    creatives: list[CreativeProposal],
    findings: list[tuple[CopyFinding, ...]],
    facts: list[AdvertFacts],
    sends_to: str,
) -> LLMResult[CopyReview]:
    from app.modules.businesses.selectors import category_label

    template, version = prompts().get(REVIEW_PROMPT)
    adverts = "\n\n".join(
        _advert(number, item, found, row)
        for number, (item, found, row) in enumerate(
            zip(creatives, findings, facts, strict=True), start=1
        )
    )
    variables: dict[str, object] = {
        "business_name": business.name,
        "business_category": category_label(business),
        "offer_text": (facts[0].offer if facts else "") or "-",
        "button_action": sends_to,
        "creative_count": str(len(creatives)),
        "adverts": adverts,
    }
    with claude() as client:
        return client.structured(
            prompt=render(template, variables),
            schema=CopyReview,
            prompt_name=REVIEW_PROMPT,
            prompt_version=version,
        )


def _advert(
    number: int,
    item: CreativeProposal,
    found: tuple[CopyFinding, ...],
    facts: AdvertFacts,
) -> str:
    flags = ", ".join(
        f"{finding.code} ({finding.detail})" if finding.detail else finding.code
        for finding in found
    )
    brief = facts.brief or "nothing of its own - the offer above is all of it"
    return (
        f"{number}.\nWhat the owner wrote about this picture: {brief}\n"
        f"primary_text: {item.primary_text}\nheadline: {item.headline}\n"
        f"description: {item.description}\nAutomatic check: {flags or 'nothing flagged'}"
    )


def _apply_review(
    launch: CampaignLaunch, *, creatives: list[CreativeProposal], review: CopyReview
) -> ReviewedCopy:
    if len(review.adverts) != len(creatives):
        logger.warning(
            "copy_review_miscounted",
            extra={"launch": str(launch.id), "asked": len(creatives)},
        )
        return ReviewedCopy(creatives=creatives)
    fixed: list[CreativeProposal] = []
    problems: list[list[dict[str, str]]] = []
    for item, advert in zip(creatives, review.adverts, strict=True):
        problems.append([problem.model_dump() for problem in advert.problems])
        if not advert.problems:
            fixed.append(item)
            continue
        fixed.append(
            CreativeProposal(
                primary_text=advert.primary_text or item.primary_text,
                headline=advert.headline or item.headline,
                description=advert.description or item.description,
            )
        )
    return ReviewedCopy(creatives=fixed, problems=problems)


def _record_review(
    db: Session, launch: CampaignLaunch, result: LLMResult[CopyReview]
) -> None:
    from app.modules.audit.services import record_llm_result

    try:
        record_llm_result(
            db,
            owner=launch.owner,
            purpose=LLMPurpose.ONBOARDING,
            result=result,
            related_type=LAUNCH_RELATED_TYPE,
            related_id=launch.id,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("llm_call_not_recorded", extra={"launch": str(launch.id)})


def _record_review_failure(db: Session, launch: CampaignLaunch, exc: LLMError) -> None:
    from app.modules.audit.services import record_llm_error

    logger.warning(
        "copy_review_skipped",
        extra={"launch": str(launch.id), "error": type(exc).__name__},
    )
    try:
        record_llm_error(
            db,
            owner=launch.owner,
            purpose=LLMPurpose.ONBOARDING,
            exc=exc,
            prompt_name=REVIEW_PROMPT,
            prompt_version=prompts().latest(REVIEW_PROMPT),
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            related_type=LAUNCH_RELATED_TYPE,
            related_id=launch.id,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("llm_call_not_recorded", extra={"launch": str(launch.id)})


def _words(item: CreativeProposal) -> AdWords:
    return AdWords(
        primary_text=item.primary_text,
        headline=item.headline,
        description=item.description,
    )
