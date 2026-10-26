"""Reading back what approved changes actually did."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.selectors.actions import account_of, managed_target
from app.modules.agent.constants import ASSESS_GIVE_UP_DAYS, ASSESS_MIN_DAYS
from app.modules.agent.models import AgentSuggestion
from app.modules.agent.selectors.outcomes import after_figures
from app.modules.agent.selectors.policy import policy_for
from app.modules.agent.selectors.suggestions import due_for_assessment
from app.modules.integrations.models import AdAccount
from core.agent import GONE, JUDGED_ON_PARENT, UNCLEAR, Policy, assess

logger = logging.getLogger(__name__)


def assess_owner(db: Session, *, owner: User, now: datetime) -> int:
    """One owner's due verdicts, under their own settings or the defaults."""
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    row = policy_for(db, owner=owner)
    policy = row.as_policy() if row is not None else Policy()
    accounts = enabled_ad_accounts(db, owner=owner)
    return assess_outcomes(
        db,
        owner=owner,
        account=accounts[0] if accounts else None,
        policy=policy,
        now=now,
    )


def assess_outcomes(
    db: Session,
    *,
    owner: User,
    account: AdAccount | None,
    policy: Policy,
    now: datetime,
) -> int:
    """Write a verdict on every change whose aftermath is old enough. Commits."""
    written = 0
    for suggestion in due_for_assessment(db, owner=owner, now=now):
        if _assess_one(
            db,
            suggestion=suggestion,
            owner=owner,
            account=account,
            policy=policy,
            now=now,
        ):
            written += 1
    db.commit()
    return written


def _assess_one(
    db: Session,
    *,
    suggestion: AgentSuggestion,
    owner: User,
    account: AdAccount | None,
    policy: Policy,
    now: datetime,
) -> bool:
    """One verdict, or a decision to wait."""
    target = managed_target(
        db,
        owner=owner,
        level=suggestion.target_level,
        external_id=suggestion.target_external_id,
    )
    if target is None:
        _write(suggestion=suggestion, outcome=GONE, figures={}, now=now)
        return True
    anchor = suggestion.decided_at or suggestion.review_at
    if anchor is None:
        return False
    level, read_id = _judged_on(suggestion)
    if not read_id:
        _write(suggestion=suggestion, outcome=UNCLEAR, figures={}, now=now)
        return True
    own = account_of(target=target, level=suggestion.target_level) or account
    after = after_figures(
        db,
        owner=owner,
        level=level,
        external_id=read_id,
        changed_at=anchor,
        tzinfo=own.tzinfo() if own is not None else UTC,
        now=now,
    )
    verdict = assess(
        rule=suggestion.rule,
        evidence=suggestion.evidence,
        after=after,
        min_days=max(policy.min_days, ASSESS_MIN_DAYS),
    )
    if verdict is None:
        if now - anchor < timedelta(days=ASSESS_GIVE_UP_DAYS):
            return False
        _write(
            suggestion=suggestion,
            outcome=UNCLEAR,
            figures={"days": after.days},
            now=now,
        )
        return True
    _write(
        suggestion=suggestion,
        outcome=verdict.outcome,
        figures=dict(verdict.figures),
        now=now,
    )
    return True


def _judged_on(suggestion: AgentSuggestion) -> tuple[str, str]:
    """Whose figures answer this promise, and at which level they are kept."""
    if suggestion.rule in JUDGED_ON_PARENT:
        return ManagedLevel.ADSET, suggestion.target_parent_id
    return suggestion.target_level, suggestion.target_external_id


def _write(
    *,
    suggestion: AgentSuggestion,
    outcome: str,
    figures: dict[str, object],
    now: datetime,
) -> None:
    suggestion.outcome = outcome
    suggestion.outcome_figures = figures
    suggestion.assessed_at = now
    logger.info("agent_outcome_assessed", extra={"outcome": outcome})


__all__ = ["assess_outcomes", "assess_owner"]
