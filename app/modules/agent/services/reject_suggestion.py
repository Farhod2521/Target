"""Saying no to a proposal."""

from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.agent.constants import OPEN_STATUSES, SuggestionStatus
from app.modules.agent.exceptions import SuggestionClosed
from app.modules.agent.models import AgentSuggestion


def reject_suggestion(
    db: Session, *, user: User, suggestion: AgentSuggestion
) -> AgentSuggestion:
    """Close one proposal without carrying it out. Caller commits."""
    if suggestion.status not in OPEN_STATUSES:
        raise SuggestionClosed
    suggestion.status = str(SuggestionStatus.REJECTED)
    suggestion.decided_at = utcnow()
    suggestion.decided_by_id = user.id
    db.flush()
    return suggestion


__all__ = ["reject_suggestion"]
