"""Turn chosen interest names into ones the provider accepts, and measure the reach."""

import hashlib
import json
import logging
from typing import Any, Final
from uuid import UUID

from adskit import AudiencePort, registry
from adskit.dto import ReachDTO
from adskit.errors import ProviderError
from adskit.refs import ExternalRef, ProviderName
from llmkit import LLMError, render
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.db import on_commit, utcnow
from app.common.llm import MECHANICAL, claude, model_for, prompts
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    LAUNCH_RELATED_TYPE,
    DraftSection,
    InterestSource,
    LaunchStep,
)
from app.modules.ads.exceptions import ConnectionUnusable, NoAdAccount
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.copy_notes import offer_text
from app.modules.ads.selectors.launches import known_terms
from app.modules.ads.services.access import launch_account_and_token
from app.modules.ads.services.targeting import (
    apply_audience_mode,
    build_for,
    chosen_interests,
    chosen_traits,
    confirm_terms,
    rebuild_targeting,
)
from app.modules.audit.constants import LLMPurpose
from app.modules.billing.exceptions import NoEntitlement
from app.modules.businesses.models import Business
from core.agent import TranslatedTerms
from core.targeting import (
    Confirmation,
    Found,
    Interest,
    apply_found,
    needs_lookup,
    stand_in_room,
    stand_ins,
)
from core.targeting import retranslate as retranslate_names

logger = logging.getLogger(__name__)
PROMPT = "interest_terms"
RELATED_TYPE = LAUNCH_RELATED_TYPE


def _business(db: Session, launch: CampaignLaunch) -> Business | None:
    from app.modules.businesses.selectors import business_for_page

    return business_for_page(db, owner=launch.owner, page=launch.page)


def _locked(db: Session, launch_id: Any) -> CampaignLaunch | None:
    return db.scalar(
        select(CampaignLaunch)
        .where(CampaignLaunch.id == launch_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


# -- confirmation ---------------------------------------------------------------------


def request_confirmation(db: Session, launch: CampaignLaunch) -> None:
    """Queue the confirmation for after this transaction commits."""
    from app.modules.ads.tasks import confirm_interests_task

    launch_id = str(launch.id)
    on_commit(db, lambda: confirm_interests_task.delay(launch_id))


def confirm_interests(db: Session, *, launch_id: UUID | str) -> str:
    """Confirm one launch's chosen interests. Returns a word for the log."""
    from app.modules.billing.services import require_preparation

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    try:
        require_preparation(db, owner=launch.owner)
    except NoEntitlement:
        return "subscription_expired"
    business = _business(db, launch)
    if business is None:
        return "profile_incomplete"
    chosen = chosen_interests(db, launch=launch)
    traits = chosen_traits(launch=launch)
    if not chosen and not traits:
        return "nothing_chosen"
    asked = _asked(chosen, traits)
    if not needs_lookup(chosen) and not needs_lookup(traits):
        stored = _store(
            db,
            launch=launch,
            business=business,
            confirmed=chosen,
            missing=(),
            traits=traits,
            traits_missing=(),
            asked=asked,
        )
        return "cached" if stored else "superseded"
    try:
        account, token = launch_account_and_token(db, launch=launch)
    except (NoAdAccount, ConnectionUnusable):
        return "no_provider"
    audiences = registry.get(launch.provider).audiences
    try:
        result = _lookup(audiences=audiences, interests=chosen, token=token)
        if result.missing:
            result = _second_attempt(
                db,
                audiences=audiences,
                launch=launch,
                business=business,
                first=result,
                token=token,
            )
        extra = (
            _stand_ins(
                db, audiences=audiences, launch=launch, result=result, token=token
            )
            if _is_ai_pick(launch)
            else ()
        )
        found = _lookup_traits(audiences=audiences, traits=traits, token=token)
    except ProviderError as exc:
        logger.warning(
            "interest confirmation failed for %s: %s", account.external_id, exc
        )
        return "provider_failed"
    if not _store(
        db,
        launch=launch,
        business=business,
        confirmed=result.all_confirmed,
        missing=result.missing,
        standing_in=extra,
        traits=found.all_confirmed,
        traits_missing=found.missing,
        asked=asked,
    ):
        return "superseded"
    return "confirmed" if not result.missing else "partial"


def _is_ai_pick(launch: CampaignLaunch) -> bool:
    proposed = draft_field.proposal(launch.draft, DraftSection.INTERESTS) or []
    ticked = draft_field.chosen(launch.draft, DraftSection.INTERESTS) or []
    return bool(proposed) and _queries(ticked) == _queries(
        draft_field.ai_picks(proposed)
    )


def _stand_ins(
    db: Session,
    *,
    audiences: AudiencePort,
    launch: CampaignLaunch,
    result: Confirmation,
    token: str,
) -> tuple[Interest, ...]:
    room = stand_in_room(kept=len(result.all_confirmed), dropped=len(result.missing))
    if not room:
        return ()
    spare = _spare(db, launch)
    if needs_lookup(spare):
        looked = _lookup(audiences=audiences, interests=spare, token=token)
        confirm_terms(
            db,
            launch=launch,
            confirmed=(),
            missing=looked.missing,
            source=InterestSource.AI,
        )
        found = {item.query: item for item in looked.all_confirmed}
        spare = tuple(found[item.query] for item in spare if item.query in found)
    return stand_ins(kept=result.all_confirmed, dropped=result.missing, spare=spare)


def _spare(db: Session, launch: CampaignLaunch) -> tuple[Interest, ...]:
    ticked = _queries(draft_field.chosen(launch.draft, DraftSection.INTERESTS) or [])
    rows = [
        item
        for item in draft_field.proposal(launch.draft, DraftSection.INTERESTS) or []
        if isinstance(item, dict)
        and str(item.get("query", "")).strip()
        and str(item.get("query", "")).strip().casefold() not in ticked
    ]
    cached = known_terms(
        db,
        owner=launch.owner,
        provider=launch.provider,
        queries=[str(item["query"]) for item in rows],
    )
    found: list[Interest] = []
    for item in rows:
        term = cached.get(str(item["query"]))
        if term is not None and not term.external_id:
            continue
        found.append(
            Interest(
                label=str(item.get("label", "")),
                query=str(item["query"]),
                external_id=term.external_id if term else "",
                audience_size=(term.audience_size or 0) if term else 0,
            )
        )
    return tuple(found)


def _chosen_row(item: Interest) -> dict[str, Any]:
    return {
        "label": item.label,
        "query": item.query,
        "external_id": item.external_id,
        "audience_size": item.audience_size,
    }


def _queries(items: list[Any]) -> frozenset[str]:
    return frozenset(
        str(item.get("query", "")).strip().casefold()
        for item in items
        if isinstance(item, dict)
    )


def _found(rows: Any) -> tuple[Found, ...]:
    return tuple(
        Found(
            name=row.name,
            external_id=row.ref.id,
            audience_lower=row.audience_lower,
            audience_upper=row.audience_upper,
        )
        for row in rows
    )


def _lookup(
    *, audiences: AudiencePort, interests: tuple[Interest, ...], token: str
) -> Confirmation:
    pending = needs_lookup(interests)
    rows = audiences.find_interests(names=list(pending), token=token)
    return apply_found(interests, _found(rows))


def _lookup_traits(
    *, audiences: AudiencePort, traits: tuple[Interest, ...], token: str
) -> Confirmation:
    if not traits:
        return Confirmation(confirmed=(), unchanged=(), missing=())
    pending = tuple(item for item in traits if not item.is_confirmed)
    already = tuple(item for item in traits if item.is_confirmed)
    rows: list[Found] = []
    for kind in sorted({item.kind for item in pending}):
        names = [item.query for item in pending if item.kind == kind]
        rows.extend(_found(audiences.find_traits(kind=kind, names=names, token=token)))
    answer = apply_found(pending, tuple(rows))
    return Confirmation(
        confirmed=answer.confirmed,
        unchanged=answer.unchanged + already,
        missing=answer.missing,
    )


def _second_attempt(
    db: Session,
    *,
    audiences: AudiencePort,
    launch: CampaignLaunch,
    business: Business,
    first: Confirmation,
    token: str,
) -> Confirmation:
    """Ask Claude what the provider calls these, then ask the provider again."""
    translations = _translate(
        db, launch=launch, business=business, missing=first.missing
    )
    if not translations:
        return first
    retried = retranslate_names(first.missing, translations)
    second = _lookup(audiences=audiences, interests=retried, token=token)
    return Confirmation(
        confirmed=first.confirmed + second.confirmed,
        unchanged=first.unchanged,
        missing=second.missing,
    )


def _translate(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    missing: tuple[Interest, ...],
) -> dict[str, str]:
    from app.modules.audit.services import record_llm_error, record_llm_result
    from app.modules.businesses.selectors import category_label

    template, version = prompts().get(PROMPT)
    text = render(
        template,
        {
            "business_category": category_label(business),
            "offer_text": offer_text(db, launch=launch, business=business) or "-",
            "typed_terms": "\n".join(f"- {item.query}" for item in missing),
        },
    )
    try:
        with claude(tier=MECHANICAL) as client:
            answer = client.structured(
                prompt=text,
                schema=TranslatedTerms,
                prompt_name=PROMPT,
                prompt_version=version,
            )
    except LLMError as exc:
        record_llm_error(
            db,
            owner=launch.owner,
            purpose=LLMPurpose.ONBOARDING,
            exc=exc,
            prompt_name=PROMPT,
            prompt_version=version,
            model=model_for(MECHANICAL),
            currency=str(settings.anthropic_price_currency),
            related_type=RELATED_TYPE,
            related_id=launch.id,
        )
        db.commit()
        logger.info("interest translation unavailable for %s", launch.id)
        return {}
    record_llm_result(
        db,
        owner=launch.owner,
        purpose=LLMPurpose.ONBOARDING,
        result=answer,
        related_type=RELATED_TYPE,
        related_id=launch.id,
    )
    db.commit()
    typed = {item.query.strip().casefold() for item in missing}
    return {
        term.label.strip().casefold(): term.query.strip()
        for term in answer.value.terms
        if term.query.strip() and term.label.strip().casefold() in typed
    }


def _store(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    confirmed: tuple[Interest, ...],
    missing: tuple[Interest, ...],
    standing_in: tuple[Interest, ...] = (),
    traits: tuple[Interest, ...] = (),
    traits_missing: tuple[Interest, ...] = (),
    asked: tuple[frozenset[str], frozenset[str]],
) -> bool:
    """The cache, the draft and the spec, in one write. ``False`` if skipped."""
    confirm_terms(
        db,
        launch=launch,
        confirmed=confirmed + standing_in,
        missing=missing,
        source=InterestSource.AI,
    )
    row = _locked(db, launch.id)
    if (
        row is None
        or _asked(chosen_interests(db, launch=row), chosen_traits(launch=row)) != asked
    ):
        db.commit()
        return False
    draft = fresh(row, "draft")
    draft_field.choose(
        draft,
        "interests",
        [_chosen_row(item) for item in confirmed]
        + [{**_chosen_row(item), draft_field.STAND_IN: True} for item in standing_in],
    )
    draft_field.set_unconfirmed(
        draft,
        "interests",
        [{"label": item.label, "query": item.query} for item in missing],
    )
    draft_field.choose(
        draft,
        DraftSection.TRAITS,
        [
            {
                "label": item.label,
                "query": item.query,
                "kind": item.kind,
                "external_id": item.external_id,
                "audience_size": item.audience_size,
            }
            for item in traits
        ],
    )
    draft_field.set_unconfirmed(
        draft,
        DraftSection.TRAITS,
        [{"label": item.label, "query": item.query} for item in traits_missing],
    )
    rebuild_targeting(db, launch=row, business=business)
    row.step = LaunchStep.INTERESTS
    request_estimate(db, row)
    db.commit()
    return True


def _asked(
    interests: tuple[Interest, ...], traits: tuple[Interest, ...]
) -> tuple[frozenset[str], frozenset[str]]:
    return (
        frozenset(item.query for item in interests),
        frozenset(item.query for item in traits),
    )


# -- the reach -------------------------------------------------------------------------


def request_estimate(db: Session, launch: CampaignLaunch) -> None:
    from app.modules.ads.tasks import estimate_audience_task

    launch_id = str(launch.id)
    on_commit(db, lambda: estimate_audience_task.delay(launch_id))


def estimate_audience(db: Session, *, launch_id: UUID | str) -> str:
    """Ask the provider how big this audience is. Returns a word for the log."""
    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    business = _business(db, launch)
    if business is None:
        return "profile_incomplete"
    if not launch.targeting:
        return "nothing_built"
    try:
        account, token = launch_account_and_token(db, launch=launch)
    except (NoAdAccount, ConnectionUnusable):
        return "no_provider"
    built = build_for(db, launch=launch, business=business)
    try:
        reach = sized(
            registry.get(launch.provider).audiences,
            account=ExternalRef(
                provider=ProviderName(launch.provider),
                level="account",
                id=account.external_id,
            ),
            targeting=dict(built.targeting),
            optimization_goal=built.optimization_goal,
            token=token,
        )
    except ProviderError as exc:
        logger.info("reach estimate unavailable for %s: %s", account.external_id, exc)
        return "provider_failed"
    if not reach.available:
        _store_reach(db, launch=launch, lower=None, upper=None)
        _settle_mode(db, launch=launch, business=business)
        return "unavailable"
    if not reach.ready:
        return "not_ready"
    _store_reach(db, launch=launch, lower=reach.lower, upper=reach.upper)
    _settle_mode(db, launch=launch, business=business)
    return "estimated"


# Meta's estimate of one spec moves slowly; a launch asks again after every save.
REACH_KEPT_SECONDS: Final = 6 * 60 * 60
REACH_KEY: Final = "reach:{fingerprint}"


def sized(
    port: Any,
    *,
    account: ExternalRef,
    targeting: dict[str, Any],
    optimization_goal: str,
    token: str,
) -> ReachDTO:
    """The provider's estimate, asked once per account, goal and spec for a few hours.

    An answer the provider has not finished is not kept: asking again is how
    it finishes.
    """
    fingerprint = hashlib.sha256(
        json.dumps(
            [account.provider, account.id, optimization_goal, targeting],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    key = REACH_KEY.format(fingerprint=fingerprint)
    kept = cache.get(key)
    if kept is not None:
        return ReachDTO.model_validate(kept)
    reach: ReachDTO = port.estimate_reach(
        account=account,
        targeting=targeting,
        optimization_goal=optimization_goal,
        token=token,
    )
    if reach.ready or not reach.available:
        cache.set(key, reach.model_dump(mode="json"), REACH_KEPT_SECONDS)
    return reach


def _settle_mode(db: Session, *, launch: CampaignLaunch, business: Business) -> None:
    row = _locked(db, launch.id)
    if row is not None and apply_audience_mode(db, launch=row, business=business):
        request_estimate(db, row)
    db.commit()


def _store_reach(
    db: Session, *, launch: CampaignLaunch, lower: int | None, upper: int | None
) -> None:
    launch.audience_lower = lower
    launch.audience_upper = upper
    launch.estimated_at = utcnow()
    launch.step = LaunchStep.ESTIMATE
    db.commit()
