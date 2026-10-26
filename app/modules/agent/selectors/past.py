"""What was proposed before about the objects on tonight's shortlist."""

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.constants import (
    OPEN_STATUSES,
    PAST_PROPOSAL_DAYS,
    PAST_PROPOSALS_PER_TARGET,
    SuggestionStatus,
)
from app.modules.agent.models import AgentSuggestion


def past_proposals(
    db: Session, *, owner: User, target_ids: Iterable[str], now: datetime
) -> dict[str, list[AgentSuggestion]]:
    """``{object id: its decided proposals, newest first}``. One query."""
    ids = {each for each in target_ids if each}
    if not ids:
        return {}
    s = AgentSuggestion
    rows = db.scalars(
        select(s)
        .where(
            s.owner_id == owner.id,
            s.target_external_id.in_(ids),
            s.created_at >= now - timedelta(days=PAST_PROPOSAL_DAYS),
            s.status.not_in([*OPEN_STATUSES, SuggestionStatus.SUPERSEDED]),
        )
        .order_by(s.created_at.desc())
    )
    found: dict[str, list[AgentSuggestion]] = {}
    for row in rows:
        kept = found.setdefault(row.target_external_id, [])
        if len(kept) < PAST_PROPOSALS_PER_TARGET:
            kept.append(row)
    return found


__all__ = ["past_proposals"]
