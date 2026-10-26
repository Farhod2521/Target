"""Proposing the fix for what the provider has stopped, as soon as it is seen."""

import logging
from datetime import datetime, timedelta

from llmkit import LLMError
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.constants import (
    AGENT_LOCK_SECONDS,
    CRASHED_CODE,
    RUN_RELATED_TYPE,
    WORDLESS_QUIET_HOURS,
    RunSource,
    RunStatus,
    SuggestionKind,
)
from app.modules.agent.models import AgentRun
from app.modules.agent.selectors.facts import account_facts
from app.modules.agent.selectors.pair_views import pair_views
from app.modules.agent.selectors.policy import policy_for
from app.modules.agent.selectors.suggestions import blocked_targets, refused_targets
from app.modules.agent.selectors.wordless import wordless_targets
from app.modules.agent.services.check_review import Reviewed, record_failure
from app.modules.agent.services.retire_suggestions import (
    withdraw_outside,
    withdraw_switched_off,
)
from app.modules.agent.services.review import review
from app.modules.agent.services.run_record import fail
from app.modules.agent.services.store_suggestions import store_suggestions
from app.modules.agent.services.write_ad_copy import with_ad_copy, writable
from app.modules.audit.constants import LLMPurpose
from app.modules.audit.services import record_llm_result
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount
from core.agent import AccountFacts, Finding, Policy, scan
from core.agent.diagnosis import Diagnosis, diagnose
from core.agent.rules import FAULT_RULES

logger = logging.getLogger(__name__)


def propose_fixes(db: Session, *, owner: User, now: datetime) -> int:
    """Propose every fix this owner does not already have. Returns how many."""
    from app.modules.ads.selectors.pages import page_scope
    from app.modules.billing.selectors.subscription import has_live_subscription
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    if not has_live_subscription(db, owner=owner):
        return 0
    key = f"agent:fixes:{owner.id}"
    if not cache.add(key, "1", AGENT_LOCK_SECONDS):
        return 0
    try:
        row = policy_for(db, owner=owner)
        policy = row.as_policy() if row is not None else Policy()
        scope = page_scope(db, owner=owner)
        withdraw_outside(db, owner=owner, outside=scope.outside, now=now)
        withdraw_switched_off(db, owner=owner, now=now)
        accounts = enabled_ad_accounts(db, owner=owner)
        views = pair_views(db, owner=owner, whole=scope, accounts=accounts)
        reads = (
            [(view.scope, account) for view in views for account in view.accounts]
            if views
            else [(scope, account) for account in accounts]
        )
        return sum(
            _account(
                db, owner=owner, account=account, policy=policy, now=now, scope=here
            )
            for here, account in reads
        )
    finally:
        cache.delete(key)


def _account(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    policy: Policy,
    now: datetime,
    scope: PageScope,
) -> int:
    facts = account_facts(
        db, owner=owner, account=account, policy=policy, now=now, scope=scope
    )
    blocked = blocked_targets(
        db, owner=owner, since=now - timedelta(hours=policy.cooldown_hours)
    ) | wordless_targets(
        db, owner=owner, since=now - timedelta(hours=WORDLESS_QUIET_HOURS)
    )
    refused = refused_targets(
        db, owner=owner, since=now - timedelta(days=policy.rejected_quiet_days)
    )
    findings = [
        finding
        for finding in scan(
            account=facts, policy=policy, blocked=blocked, refused=refused
        )
        if finding.rule in FAULT_RULES
    ]
    if not findings:
        return 0
    run = AgentRun(
        owner_id=owner.id,
        source=RunSource.FAULT,
        window_days=policy.window_days,
        status=RunStatus.RUNNING,
        considered=len(findings),
        found=len(findings),
    )
    db.add(run)
    db.commit()
    try:
        return _fix(
            db,
            run=run,
            owner=owner,
            facts=facts,
            findings=findings,
            policy=policy,
            now=now,
        )
    except Exception:
        fail(db, run, code=CRASHED_CODE)
        raise


def _fix(
    db: Session,
    *,
    run: AgentRun,
    owner: User,
    facts: AccountFacts,
    findings: list[Finding],
    policy: Policy,
    now: datetime,
) -> int:
    from app.modules.billing.selectors.promo import ai_budget
    from app.modules.businesses.selectors import business_for

    causes = {each.adset_id: each for each in diagnose(account=facts, policy=policy)}
    business = business_for(db, owner)
    can_ask = (
        business is not None and not ai_budget(db, owner=owner, now=now).is_exhausted
    )
    if business is not None and can_ask:
        findings = writable(
            db, user=owner, run=run, business=business, findings=findings
        )
    plain = [Reviewed(finding=finding, reason="", keep=True) for finding in findings]
    if not plain:
        explained: list[Reviewed] = []
    elif business is None or not can_ask:
        explained = [
            item for item in plain if item.finding.kind != SuggestionKind.NEW_AD
        ]
    else:
        explained = with_ad_copy(
            db,
            user=owner,
            run=run,
            business=business,
            reviewed=_explained(
                db,
                owner=owner,
                run=run,
                facts=facts,
                business=business,
                causes=causes,
                plain=plain,
            ),
        )
    run.status = str(RunStatus.DONE)
    run.finished_at = utcnow()
    run.proposed = len(
        store_suggestions(db, run=run, reviewed=explained, now=now, causes=causes)
    )
    return run.proposed


def _explained(
    db: Session,
    *,
    owner: User,
    run: AgentRun,
    facts: AccountFacts,
    business: Business,
    causes: dict[str, Diagnosis],
    plain: list[Reviewed],
) -> list[Reviewed]:
    """The findings with Claude's sentence where one can be had - all of them."""
    try:
        reviewed, result = review(
            account=facts,
            business=business,
            findings=[item.finding for item in plain],
            language=owner.language,
            causes=causes,
        )
    except LLMError as exc:
        logger.warning("fault_review_failed", extra={"run": str(run.id)})
        run.llm_cost_minor = record_failure(db, owner=owner, run_id=run.id, exc=exc)
        return plain
    record_llm_result(
        db,
        owner=owner,
        purpose=LLMPurpose.DECISION,
        result=result,
        related_type=RUN_RELATED_TYPE,
        related_id=run.id,
    )
    run.llm_cost_minor = result.cost_minor
    run.currency = result.currency
    return [
        Reviewed(finding=item.finding, reason=item.reason, keep=True)
        for item in reviewed
    ]


__all__ = ["propose_fixes"]
