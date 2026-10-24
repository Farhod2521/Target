"""Carrying out a proposal, after checking it is still the right one against tonight's account."""

import logging
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.agent.advert_words import AdvertWords
from app.modules.agent.constants import (
    OPEN_STATUSES,
    REASON_ON_EARLIER_FIGURES,
    STALE_CHANGED,
    STALE_GONE,
    STALE_LABELS,
    STALE_OUTSIDE,
    WORDS_NOT_SHOWN,
    SuggestionKind,
    SuggestionStatus,
)
from app.modules.agent.exceptions import (
    SuggestionClosed,
    SuggestionStale,
    WordsNotShown,
)
from app.modules.agent.models import AgentSuggestion
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount
from core.agent import Finding, Policy, holds, scan

logger = logging.getLogger(__name__)


def approve_suggestion(
    db: Session,
    *,
    user: User,
    suggestion: AgentSuggestion,
    words: AdvertWords | None = None,
) -> ActionLog:
    """Say yes to one proposal, and make the change it asks for."""
    now = utcnow()
    _open_or_refuse(suggestion=suggestion)
    if suggestion.kind == SuggestionKind.NEW_AD and words is None:
        raise WordsNotShown(str(WORDS_NOT_SHOWN))
    fresh, policy = _still_holds(db, user=user, suggestion=suggestion, now=now)
    with db.begin_nested():
        log = carry_out(
            db, user=user, suggestion=suggestion, finding=fresh, words=words
        )
        suggestion.status = SuggestionStatus.APPROVED
        suggestion.decided_at = now
        suggestion.decided_by_id = user.id
        suggestion.action_log_id = log.id
        suggestion.evidence = _used(before=suggestion.evidence, fresh=fresh.evidence)
        suggestion.payload = sent(suggestion=suggestion, finding=fresh, words=words)
        suggestion.review_at = now + timedelta(hours=policy.cooldown_hours)
        db.flush()
    return log


def _open_or_refuse(*, suggestion: AgentSuggestion) -> None:
    """Refuse a second press. Nothing else - lateness is not a refusal."""
    if suggestion.status not in OPEN_STATUSES:
        raise SuggestionClosed


def _still_holds(
    db: Session, *, user: User, suggestion: AgentSuggestion, now: datetime
) -> tuple[Finding, Policy]:
    """Tonight's version of this proposal, or a refusal."""
    from app.modules.ads.selectors import page_scope
    from app.modules.agent.selectors.facts import account_facts
    from app.modules.agent.selectors.policy import policy_for

    if page_scope(db, owner=user).hides_adset(_group_of(suggestion)):
        _mark_stale(
            db,
            suggestion=suggestion,
            reason=STALE_OUTSIDE,
            now=now,
            by=user,
            status=SuggestionStatus.SUPERSEDED,
        )
        raise SuggestionStale(str(STALE_LABELS[STALE_OUTSIDE]))
    account = _account_of(db, user=user, suggestion=suggestion)
    if account is None:
        _mark_stale(db, suggestion=suggestion, reason=STALE_GONE, now=now, by=user)
        raise SuggestionStale(str(STALE_LABELS[STALE_GONE]))
    policy_row = policy_for(db, owner=user)
    policy = policy_row.as_policy() if policy_row is not None else Policy()
    facts = account_facts(db, owner=user, account=account, policy=policy, now=now)
    fresh = holds(
        finding=_as_finding(suggestion), found=scan(account=facts, policy=policy)
    )
    if fresh is None or fresh.kind != suggestion.kind:
        _mark_stale(db, suggestion=suggestion, reason=STALE_CHANGED, now=now, by=user)
        raise SuggestionStale(str(STALE_LABELS[STALE_CHANGED]))
    return fresh, policy


def _account_of(
    db: Session, *, user: User, suggestion: AgentSuggestion
) -> AdAccount | None:
    """The ad account the proposal's object spends from, read from the mirror."""
    from app.modules.ads.selectors.actions import account_of, managed_target

    target = managed_target(
        db,
        owner=user,
        level=suggestion.target_level,
        external_id=suggestion.target_external_id,
    )
    if target is None:
        return None
    return account_of(target=target, level=suggestion.target_level)


def _used(*, before: Mapping[str, Any], fresh: Mapping[str, Any]) -> dict[str, Any]:
    """The approval's figures, marked where they differ from the proposal's."""
    used = dict(fresh)
    earlier = {
        key: value
        for key, value in (before or {}).items()
        if key != REASON_ON_EARLIER_FIGURES
    }
    if earlier != used:
        used[REASON_ON_EARLIER_FIGURES] = True
    return used


def _group_of(suggestion: AgentSuggestion) -> str:
    if suggestion.target_level == ManagedLevel.AD:
        return suggestion.target_parent_id
    return suggestion.target_external_id


def _as_finding(suggestion: AgentSuggestion) -> Finding:
    """The stored row as the domain value the rules compare against: rule and object only."""
    return Finding(
        kind=suggestion.kind,  # type: ignore[arg-type]
        rule=suggestion.rule,
        ref=suggestion.to_ref(),
    )


def _mark_stale(
    db: Session,
    *,
    suggestion: AgentSuggestion,
    reason: str,
    now: datetime,
    by: User | None = None,
    status: str = SuggestionStatus.STALE,
) -> None:
    """Close a proposal the account has moved past. Committed: the refusal must stay."""
    suggestion.status = status
    suggestion.stale_reason = reason
    suggestion.decided_at = now
    suggestion.decided_by_id = by.id if by is not None else None
    db.commit()
    logger.info("agent_suggestion_stale", extra={"reason": reason})


def carry_out(
    db: Session,
    *,
    user: User,
    suggestion: AgentSuggestion,
    finding: Finding,
    words: AdvertWords | None,
) -> ActionLog:
    """Hand the change to the ordinary management path."""
    from app.modules.ads.services import (
        by_agent,
        request_budget,
        request_pause,
        request_resume,
        request_swap,
        request_targeting,
    )

    origin = by_agent(str(suggestion.run_id))
    external_id = suggestion.target_external_id
    if finding.kind == SuggestionKind.PAUSE:
        return request_pause(
            db,
            user=user,
            level=suggestion.target_level,
            external_id=external_id,
            origin=origin,
        )
    if finding.kind == SuggestionKind.RESUME:
        return request_resume(
            db,
            user=user,
            level=suggestion.target_level,
            external_id=external_id,
            origin=origin,
        )
    if finding.kind in (
        SuggestionKind.SWAP_TARGETING,
        SuggestionKind.NARROW_TARGETING,
        SuggestionKind.DROP_AUDIENCE,
    ):
        return request_targeting(
            db,
            user=user,
            external_id=external_id,
            targeting=dict(finding.payload["targeting"]),
            step=str(finding.payload.get("step", "")),
            origin=origin,
        )
    if finding.kind == SuggestionKind.NEW_PICTURE:
        return request_swap(
            db,
            user=user,
            external_id=external_id,
            asset_id=str(finding.payload["asset_id"]),
            origin=origin,
        )
    if finding.kind == SuggestionKind.NEW_AD and words is not None:
        return request_swap(
            db,
            user=user,
            external_id=external_id,
            message=words.message,
            headline=words.headline,
            description=words.description,
            asset_id=words.asset_id,
            origin=origin,
        )
    return request_budget(
        db,
        user=user,
        level=suggestion.target_level,
        external_id=external_id,
        daily_budget_minor=int(finding.payload["daily_budget_minor"]),
        origin=origin,
    )


def sent(
    *, suggestion: AgentSuggestion, finding: Finding, words: AdvertWords | None
) -> dict[str, Any]:
    """What the write carried; a new advert keeps the words proposed and saved."""
    if words is None:
        return dict(finding.payload)
    return {**(suggestion.payload or {}), "sent": asdict(words)}


__all__ = ["approve_suggestion", "carry_out", "sent"]
