"""Refused adverts the agent recently could not write new words for."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.constants import NO_WORDS_PREFIX
from app.modules.agent.models import AgentRun


def wordless_targets(db: Session, *, owner: User, since: datetime) -> set[str]:
    """Adverts a pass since ``since`` dropped for want of words."""
    rows = db.scalars(
        select(AgentRun.dropped).where(
            AgentRun.owner_id == owner.id, AgentRun.created_at >= since
        )
    )
    return {
        str(entry.get("target", ""))
        for dropped in rows
        for entry in dropped or []
        if isinstance(entry, dict)
        and str(entry.get("reason", "")).startswith(NO_WORDS_PREFIX)
    }


__all__ = ["wordless_targets"]
