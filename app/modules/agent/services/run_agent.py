"""One night's pass over one owner's advertising. Worker-side; commits."""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.constants import (
    AGENT_LOCK_SECONDS,
    CRASHED_CODE,
    RunStatus,
    SkipReason,
)
from app.modules.agent.exceptions import AgentAlreadyRunning
from app.modules.agent.models import AgentPolicy, AgentRun
from app.modules.agent.selectors.pair_views import pair_views
from app.modules.agent.selectors.policy import policy_for, stale_accounts
from app.modules.agent.selectors.strategy import strategy_state
from app.modules.agent.selectors.suggestions import blocked_targets, refused_targets
from app.modules.agent.services.assess_outcomes import assess_outcomes
from app.modules.agent.services.repair_account import repair_account
from app.modules.agent.services.retire_suggestions import (
    retire_suggestions,
    withdraw_outside,
    withdraw_switched_off,
)
from app.modules.agent.services.review_findings import (
    review_findings,
    shelves_for,
    shortlist,
)
from app.modules.agent.services.run_record import close, fail, skip, stamp
from app.modules.agent.services.save_policy import save_policy
from app.modules.agent.services.store_suggestions import store_suggestions
from app.modules.integrations.models import AdAccount
from core.agent import Policy
from core.strategy import advise, maturity

logger = logging.getLogger(__name__)


def run_agent(db: Session, *, user: User) -> AgentRun | None:
    """Look at every account in the subscription and propose what should change."""
    policy_row = policy_for(db, owner=user)
    if policy_row is None:
        policy_row = save_policy(db, user=user, is_enabled=True)
        db.commit()
    if not policy_row.is_enabled:
        return None
    key = f"agent:run:{user.id}"
    if not cache.add(key, "1", AGENT_LOCK_SECONDS):
        raise AgentAlreadyRunning
    try:
        return _pass(db, user=user, policy_row=policy_row)
    finally:
        cache.delete(key)


def _pass(db: Session, *, user: User, policy_row: AgentPolicy) -> AgentRun:
    """Open the row, walk the account, and close the row either way."""
    now = utcnow()
    run = AgentRun(
        owner_id=user.id, window_days=policy_row.window_days, status=RunStatus.RUNNING
    )
    db.add(run)
    db.commit()
    try:
        return _walk(db, run=run, user=user, policy_row=policy_row, now=now)
    except Exception:
        fail(db, run, code=CRASHED_CODE)
        raise


def _walk(
    db: Session, *, run: AgentRun, user: User, policy_row: AgentPolicy, now: datetime
) -> AgentRun:
    from app.modules.ads.selectors.pages import page_scope
    from app.modules.billing.selectors.promo import ai_budget
    from app.modules.billing.selectors.subscription import has_live_subscription
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    retire_suggestions(db, owner=user, now=now)
    if not has_live_subscription(db, owner=user):
        return skip(db, run, SkipReason.EXPIRED)
    repair_account(db, owner=user, now=now)
    accounts = enabled_ad_accounts(db, owner=user)
    if not accounts:
        return skip(db, run, SkipReason.NO_ACCOUNT)
    home = accounts[0]
    policy = policy_row.as_policy()
    assess_outcomes(db, owner=user, account=home, policy=policy, now=now)
    budget = ai_budget(db, owner=user, now=now)
    scope = page_scope(db, owner=user)
    withdraw_outside(db, owner=user, outside=scope.outside, now=now)
    withdraw_switched_off(db, owner=user, now=now)
    _advise(db, run=run, user=user, whole=scope, account=home, policy=policy, now=now)
    if budget.is_exhausted:
        return skip(db, run, SkipReason.LIMIT)
    stale = stale_accounts(db, owner=user, accounts=accounts, now=now)
    fresh = [account for account in accounts if account not in stale]
    if not fresh:
        return skip(db, run, SkipReason.STALE)
    blocked = blocked_targets(
        db, owner=user, since=now - timedelta(hours=policy.cooldown_hours)
    )
    refused = refused_targets(
        db, owner=user, since=now - timedelta(days=policy.rejected_quiet_days)
    )
    shelves = shelves_for(
        db,
        user=user,
        run=run,
        whole=scope,
        fresh=fresh,
        policy=policy,
        blocked=frozenset(blocked),
        refused=frozenset(refused),
        now=now,
    )
    if not shelves or run.considered == 0:
        return skip(db, run, SkipReason.NO_DATA)
    chosen = shortlist(shelves, policy=policy)
    run.found = sum(len(findings) for _facts, findings in chosen)
    if run.found == 0:
        return skip(db, run, SkipReason.NOTHING)
    answers = review_findings(
        db, user=user, run=run, chosen=chosen, policy=policy, now=now
    )
    if not answers.answered:
        return skip(
            db, run, SkipReason.LIMIT if answers.limited else SkipReason.AI_UNAVAILABLE
        )
    run.proposed = len(
        store_suggestions(
            db, run=run, reviewed=answers.kept, now=now, causes=answers.causes
        )
    )
    close(db, run, SkipReason.NOTHING if run.proposed == 0 else "")
    stamp(db, policy_row, now)
    return run


def _advise(
    db: Session,
    *,
    run: AgentRun,
    user: User,
    whole: PageScope,
    account: AdAccount,
    policy: Policy,
    now: datetime,
) -> None:
    """What each pair of the subscription should do next, pair by pair."""
    views = pair_views(db, owner=user, whole=whole, accounts=[account])
    reads: list[tuple[str, str, PageScope | None]] = [
        (view.key, view.page, view.scope) for view in views
    ] or [("", "", None)]
    records: list[dict[str, object]] = []
    for key, page_id, scope in reads:
        state = strategy_state(
            db, owner=user, account=account, policy=policy, now=now, scope=scope
        )
        records += [{**item.as_record(), "page": key} for item in advise(state=state)]
        if page_id == whole.current or not run.maturity:
            run.maturity = maturity(history=state.history)
    run.advice = records


__all__ = ["run_agent"]
