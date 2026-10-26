"""Closing a night's run row, and stamping the settings row beside it.

Worker-side: each write commits, as the Django version's saves did.
"""

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.agent.constants import RunStatus, SkipReason
from app.modules.agent.models import AgentPolicy, AgentRun

logger = logging.getLogger(__name__)


def skip(db: Session, run: AgentRun, reason: SkipReason) -> AgentRun:
    """Close the run without proposing anything, and say why."""
    close(db, run, reason)
    stamp_owner(db, run)
    return run


def fail(db: Session, run: AgentRun, *, code: str) -> None:
    """Close the run as broken, so the screen has something to read."""
    db.rollback()
    now = utcnow()
    db.execute(
        update(AgentRun)
        .where(AgentRun.id == run.id)
        .values(
            status=RunStatus.FAILED, error_code=code, finished_at=now, updated_at=now
        )
    )
    db.commit()
    logger.warning("agent_run_failed", extra={"run": str(run.id), "code": code})


def close(db: Session, run: AgentRun, reason: SkipReason | str) -> None:
    run.status = str(RunStatus.DONE)
    run.skip_reason = str(reason)
    run.finished_at = utcnow()
    db.commit()


def stamp_owner(db: Session, run: AgentRun) -> None:
    """Record the attempt on the settings row, even a fruitless one."""
    row = db.scalar(select(AgentPolicy).where(AgentPolicy.owner_id == run.owner_id))
    if row is not None:
        stamp(db, row, run.finished_at or utcnow())


def stamp(db: Session, policy_row: AgentPolicy, moment: datetime) -> None:
    policy_row.last_run_at = moment
    db.commit()


__all__ = ["close", "fail", "skip", "stamp", "stamp_owner"]
