"""Reads over what the agent has done, night by night."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.constants import RECENT_RUNS, RunSource, RunStatus, SkipReason
from app.modules.agent.models import AgentRun

BROKEN_NOTE = "Ko'rik tugamadi"
QUIET_NOTE = "O'zgartirish kerak emas"


@dataclass(frozen=True, slots=True)
class RunLine:
    """One night as the history list draws it."""

    when: datetime
    proposed: int
    note: Any
    broken: bool = False


def _nights(owner: User) -> Select[tuple[AgentRun]]:
    return select(AgentRun).where(
        AgentRun.owner_id == owner.id, AgentRun.source == RunSource.NIGHT
    )


def recent(
    db: Session, *, owner: User, limit: int = RECENT_RUNS
) -> tuple[RunLine, ...]:
    """The last few passes, newest first."""
    rows = db.scalars(_nights(owner).order_by(AgentRun.created_at.desc()).limit(limit))
    return tuple(_line(row) for row in rows)


def _line(row: AgentRun) -> RunLine:
    broken = row.status == RunStatus.FAILED
    skipped = SkipReason(row.skip_reason).label if row.skip_reason else ""
    return RunLine(
        when=row.created_at,
        proposed=row.proposed,
        note=BROKEN_NOTE if broken else (skipped or QUIET_NOTE),
        broken=broken,
    )


def last(db: Session, *, owner: User) -> AgentRun | None:
    """The most recent pass, for the "last checked" line."""
    return db.scalar(_nights(owner).order_by(AgentRun.created_at.desc()).limit(1))


def is_running(db: Session, *, owner: User) -> bool:
    return (
        db.scalar(_nights(owner).where(AgentRun.status == RunStatus.RUNNING).limit(1))
        is not None
    )


def finished_since(db: Session, *, owner: User, since: datetime) -> bool:
    """Whether a pass that started at or after ``since`` reached a conclusion."""
    return (
        db.scalar(
            _nights(owner)
            .where(
                AgentRun.created_at >= since,
                AgentRun.finished_at.is_not(None),
                AgentRun.status == RunStatus.DONE,
            )
            .limit(1)
        )
        is not None
    )


__all__ = [
    "BROKEN_NOTE",
    "QUIET_NOTE",
    "RunLine",
    "finished_since",
    "is_running",
    "last",
    "recent",
]
