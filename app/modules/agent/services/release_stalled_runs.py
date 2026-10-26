"""Close the passes nothing else can close."""

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.agent.constants import (
    RUN_STALLED_AFTER_MINUTES,
    STALLED_CODE,
    RunStatus,
)
from app.modules.agent.models import AgentRun

logger = logging.getLogger(__name__)


def release_stalled_runs(db: Session) -> int:
    """Mark long-running passes failed. Returns how many. Commits."""
    now = utcnow()
    cutoff = now - timedelta(minutes=RUN_STALLED_AFTER_MINUTES)
    stalled = (AgentRun.status == RunStatus.RUNNING, AgentRun.created_at < cutoff)
    frozen = db.execute(select(AgentRun.id, AgentRun.source).where(*stalled)).all()
    if not frozen:
        return 0
    db.execute(
        update(AgentRun)
        .where(AgentRun.id.in_([pk for pk, _source in frozen]))
        .values(
            status=RunStatus.FAILED,
            error_code=STALLED_CODE,
            finished_at=now,
            updated_at=now,
        )
    )
    db.commit()
    for pk, source in frozen:
        logger.warning("agent_run_stalled", extra={"run": str(pk), "source": source})
    return len(frozen)


__all__ = ["release_stalled_runs"]
