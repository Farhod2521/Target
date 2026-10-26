"""Moving proposals along when nobody answers them. Each move commits."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.agent.constants import (
    OPEN_STATUSES,
    UNANSWERED_KEEP_DAYS,
    SuggestionKind,
    SuggestionStatus,
)
from app.modules.agent.models import AgentSuggestion
from app.modules.agent.selectors.suggestions import switched_off
from core.agent.rules import REFRESH_AD

WITHDRAWN: tuple[tuple[str, str], ...] = ((REFRESH_AD, SuggestionKind.NEW_AD),)
_ASKING = (SuggestionStatus.PENDING, SuggestionStatus.UNANSWERED)


@dataclass(frozen=True, slots=True)
class Retired:
    """How many rows each move touched. Counts, for the log and the tests."""

    unanswered: int = 0
    closed: int = 0
    withdrawn: int = 0


def _move(db: Session, owner: User, *where: Any, status: str, now: datetime) -> int:
    result = db.execute(
        update(AgentSuggestion)
        .where(AgentSuggestion.owner_id == owner.id, *where)
        .values(status=status, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def retire_suggestions(db: Session, *, owner: User, now: datetime) -> Retired:
    """Move what the clock has moved on. Returns what each step touched."""
    s = AgentSuggestion
    unanswered = _move(
        db,
        owner,
        s.status == SuggestionStatus.PENDING,
        s.expires_at <= now,
        status=SuggestionStatus.UNANSWERED,
        now=now,
    )
    closed = _move(
        db,
        owner,
        s.status == SuggestionStatus.UNANSWERED,
        s.created_at <= now - timedelta(days=UNANSWERED_KEEP_DAYS),
        status=SuggestionStatus.EXPIRED,
        now=now,
    )
    withdrawn = 0
    for rule, kind in WITHDRAWN:
        withdrawn += _move(
            db,
            owner,
            s.status.in_(_ASKING),
            s.rule == rule,
            s.kind == kind,
            status=SuggestionStatus.SUPERSEDED,
            now=now,
        )
    db.commit()
    return Retired(unanswered=unanswered, closed=closed, withdrawn=withdrawn)


def withdraw_outside(
    db: Session, *, owner: User, outside: Collection[str], now: datetime
) -> int:
    """Close the open proposals about groups the subscription does not cover."""
    if not outside:
        return 0
    groups = list(outside)
    s = AgentSuggestion
    moved = _move(
        db,
        owner,
        s.status.in_(OPEN_STATUSES),
        or_(
            and_(
                s.target_level == ManagedLevel.ADSET, s.target_external_id.in_(groups)
            ),
            and_(s.target_level == ManagedLevel.AD, s.target_parent_id.in_(groups)),
        ),
        status=SuggestionStatus.SUPERSEDED,
        now=now,
    )
    db.commit()
    return moved


def withdraw_switched_off(db: Session, *, owner: User, now: datetime) -> int:
    """Close the open proposals about something switched off since."""
    moved = _move(
        db,
        owner,
        AgentSuggestion.status.in_(OPEN_STATUSES),
        switched_off(owner),
        status=SuggestionStatus.SUPERSEDED,
        now=now,
    )
    db.commit()
    return moved


def supersede_suggestions(
    db: Session, *, owner: User, target_external_id: str, rule: str, now: datetime
) -> int:
    """Retire the open proposals a fresher one about the same thing replaces."""
    s = AgentSuggestion
    return _move(
        db,
        owner,
        s.status.in_(_ASKING),
        s.target_external_id == target_external_id,
        s.rule == rule,
        status=SuggestionStatus.SUPERSEDED,
        now=now,
    )


__all__ = [
    "Retired",
    "retire_suggestions",
    "supersede_suggestions",
    "withdraw_outside",
    "withdraw_switched_off",
]
