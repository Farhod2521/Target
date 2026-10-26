"""Putting right the few things the agent is allowed to put right."""

import logging
from dataclasses import dataclass
from datetime import datetime
from hashlib import md5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.agent.constants import FIX_ACTIONS
from app.modules.agent.models import AgentFix
from app.modules.agent.selectors.policy import policy_for
from app.modules.agent.selectors.repairs import Trouble, repairable
from app.modules.audit.constants import ActionStatus, ActorType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from core.agent.autofix import LEADS_RECOVERABLE, PAGE_UNSUBSCRIBED, fix_for

logger = logging.getLogger(__name__)
FIX_LEVEL = "account"
FIX_PROVIDER = "meta"


@dataclass(frozen=True, slots=True)
class Repaired:
    """What one pass over one account mended."""

    fixes: tuple[AgentFix, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.fixes)


def repair_account(db: Session, *, owner: User, now: datetime) -> Repaired:
    """Mend what may be mended here, and write down that it was. Commits."""
    policy = policy_for(db, owner=owner)
    if policy is None or not policy.self_repair:
        return Repaired()
    made: list[AgentFix] = []
    for trouble in repairable(db, owner=owner, now=now):
        fix = fix_for(trouble.trigger)
        if fix is None:
            continue
        key = _key(owner=owner, trigger=trouble.trigger, now=now)
        seen = db.scalar(
            select(ActionLog.id).where(
                ActionLog.owner_id == owner.id, ActionLog.idempotency_key == key
            )
        )
        if seen is not None:
            continue
        row = _carry_out(
            db, owner=owner, trouble=trouble, action=fix.action, key=key, now=now
        )
        if row is not None:
            made.append(row)
    return Repaired(fixes=tuple(made))


def _key(*, owner: User, trigger: str, now: datetime) -> str:
    """One repair, one account, one trigger, one day."""
    seed = f"{owner.id}:{trigger}:{now:%Y-%m-%d}"
    return f"fix:{md5(seed.encode(), usedforsecurity=False).hexdigest()}"


def _carry_out(
    db: Session, *, owner: User, trouble: Trouble, action: str, key: str, now: datetime
) -> AgentFix | None:
    """One repair: do it, and leave three rows saying so."""
    try:
        done = _run(db, owner=owner, trouble=trouble, now=now)
    except DomainError as exc:
        db.rollback()
        logger.info(
            "agent_fix_refused",
            extra={"trigger": trouble.trigger, "reason": type(exc).__name__},
        )
        return None
    if not done:
        db.commit()
        return None
    log = ActionLog(
        owner_id=owner.id,
        actor_type=ActorType.AGENT,
        action=FIX_ACTIONS[action],
        target_provider=FIX_PROVIDER,
        target_level=FIX_LEVEL,
        target_external_id=trouble.target_id,
        request_payload=dict(trouble.detail),
        previous_state=dict(trouble.previous),
        idempotency_key=key,
        status=ActionStatus.APPLIED,
        applied_at=now,
    )
    row = AgentFix(
        owner_id=owner.id,
        trigger=trouble.trigger,
        action=action,
        target_id=trouble.target_id,
        detail=dict(trouble.detail),
        previous=dict(trouble.previous),
    )
    db.add_all([log, row])
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.AGENT_FIX_APPLIED,
        aggregate_type="agent_fix",
        aggregate_id=row.id,
        payload={"trigger": trouble.trigger, "action": action},
    )
    db.commit()
    logger.info(
        "agent_fix_applied",
        extra={"trigger": trouble.trigger, "action": action, "log": str(log.id)},
    )
    return row


def _run(db: Session, *, owner: User, trouble: Trouble, now: datetime) -> bool:
    """Hand the repair to the service that owns it."""
    from app.modules.integrations.selectors.connection import active_page
    from app.modules.leads.services import recheck_page, recover_leads

    if trouble.trigger == PAGE_UNSUBSCRIBED:
        page = active_page(db, owner=owner)
        if page is None:
            return False
        recheck_page(db, page=page, actor_id="agent")
        return True
    if trouble.trigger == LEADS_RECOVERABLE:
        return recover_leads(db, user=owner, now=now) > 0
    return False


__all__ = ["Repaired", "repair_account"]
