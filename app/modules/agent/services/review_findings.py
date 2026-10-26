"""Tonight's shortlist, page by page, and what Claude says about it."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from llmkit import LLMError
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.ads.selectors.pages import pages_advertising
from app.modules.agent.constants import RUN_RELATED_TYPE
from app.modules.agent.models import AgentRun
from app.modules.agent.past import past_block
from app.modules.agent.selectors.facts import account_facts
from app.modules.agent.selectors.past import past_proposals
from app.modules.agent.services.check_review import Reviewed, record_failure
from app.modules.agent.services.review import review
from app.modules.agent.services.write_ad_copy import with_ad_copy, writable
from app.modules.audit.constants import LLMPurpose
from app.modules.audit.services import record_llm_result
from app.modules.billing.selectors.promo import ai_budget
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import business_for_page
from app.modules.integrations.models import AdAccount
from core.agent import AccountFacts, Finding, Policy, cap, scan
from core.agent.diagnosis import Diagnosis, diagnose

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Shelf:
    """One page's facts on one account, and what the rules noticed there."""

    facts: AccountFacts
    found: list[Finding]
    business: Business
    page: str = ""
    pair: str = ""


@dataclass(slots=True)
class Answers:
    """What the review said, gathered across every account it was asked about."""

    kept: list[Reviewed] = field(default_factory=list)
    causes: dict[str, Diagnosis] = field(default_factory=dict)
    answered: bool = False
    limited: bool = False


def shortlist(
    shelves: list[Shelf], *, policy: Policy
) -> list[tuple[Shelf, list[Finding]]]:
    """Tonight's proposals, capped once **per pair**."""
    kept: set[int] = set()
    for pair in {shelf.pair for shelf in shelves}:
        here = [shelf for shelf in shelves if shelf.pair == pair]
        ranked = sorted(
            (item for shelf in here for item in shelf.found),
            key=lambda item: (-item.weight, item.ref.id),
        )
        kept |= {id(item) for item in cap(iter(ranked), policy=policy)}
    return [
        (shelf, [item for item in shelf.found if id(item) in kept])
        for shelf in shelves
        if any(id(item) in kept for item in shelf.found)
    ]


def shelves_for(
    db: Session,
    *,
    user: User,
    run: AgentRun,
    whole: PageScope,
    fresh: list[AdAccount],
    policy: Policy,
    blocked: frozenset[str],
    refused: frozenset[str],
    now: datetime,
) -> list[Shelf]:
    """One shelf per page and paying account, each with that page's profile."""
    fresh_ids = {account.id for account in fresh}
    shelves: list[Shelf] = []
    for view in pages_advertising(db, owner=user):
        if view.page is None:
            continue
        business = business_for_page(db, owner=user, page=view.page)
        if business is None:
            logger.info(
                "agent_page_undescribed",
                extra={"run": str(run.id), "page": view.page.external_id},
            )
            continue
        page = view.page.external_id
        paired = view.pair_account.external_id if view.pair_account else ""
        here = whole.only(page, paired)
        pair = page if view.first_pair or not paired else f"{page}:{paired}"
        for account in view.accounts:
            if account.id not in fresh_ids:
                continue
            facts = account_facts(
                db, owner=user, account=account, policy=policy, now=now, scope=here
            )
            run.considered += sum(
                1 for item in facts.adsets if item.days_with_spend >= policy.min_days
            )
            shelves.append(
                Shelf(
                    facts=facts,
                    found=scan(
                        account=facts, policy=policy, blocked=blocked, refused=refused
                    ),
                    business=business,
                    page=page,
                    pair=pair,
                )
            )
    return shelves


def review_findings(
    db: Session,
    *,
    user: User,
    run: AgentRun,
    chosen: list[tuple[Shelf, list[Finding]]],
    policy: Policy,
    now: datetime,
) -> Answers:
    """Ask Claude about each shelf's shortlist and keep what survives."""
    answers = Answers()
    run.dropped = []
    for shelf, findings in chosen:
        if ai_budget(db, owner=user, now=now).is_exhausted:
            answers.limited = True
            logger.info("agent_review_limit_reached", extra={"run": str(run.id)})
            break
        _ask(
            db,
            user=user,
            run=run,
            business=shelf.business,
            facts=shelf.facts,
            findings=findings,
            policy=policy,
            answers=answers,
            now=now,
        )
    return answers


def _ask(
    db: Session,
    *,
    user: User,
    run: AgentRun,
    business: Business,
    facts: AccountFacts,
    findings: list[Finding],
    policy: Policy,
    answers: Answers,
    now: datetime,
) -> None:
    """One shelf's call, folded into the night's answers."""
    findings = writable(db, user=user, run=run, business=business, findings=findings)
    if not findings:
        answers.answered = True
        return
    found_causes = {
        each.adset_id: each for each in diagnose(account=facts, policy=policy)
    }
    past = past_proposals(
        db,
        owner=user,
        target_ids=[id_ for each in findings for id_ in (each.ref.id, each.parent_id)],
        now=now,
    )
    try:
        reviewed, result = review(
            account=facts,
            business=business,
            findings=findings,
            language=user.language,
            causes=found_causes,
            history=lambda part: past_block(
                findings=part, past=past, now=now, currency=facts.currency
            ),
        )
    except LLMError as exc:
        logger.warning("agent_review_failed", extra={"run": str(run.id)})
        run.llm_cost_minor += record_failure(db, owner=user, run_id=run.id, exc=exc)
        return
    answers.answered = True
    record_llm_result(
        db,
        owner=user,
        purpose=LLMPurpose.DECISION,
        result=result,
        related_type=RUN_RELATED_TYPE,
        related_id=run.id,
    )
    run.llm_cost_minor += result.cost_minor
    run.currency = result.currency
    answers.causes.update(found_causes)
    answers.kept += with_ad_copy(
        db,
        user=user,
        run=run,
        business=business,
        reviewed=[item for item in reviewed if item.keep],
    )
    run.dropped = [
        *(run.dropped or []),
        *(
            {
                "rule": item.finding.rule,
                "target": item.finding.ref.id,
                "reason": item.reason,
            }
            for item in reviewed
            if not item.keep
        ),
    ]


__all__ = ["Answers", "Shelf", "review_findings", "shelves_for", "shortlist"]
