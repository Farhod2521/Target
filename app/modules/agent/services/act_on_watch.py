"""Pressing one of the buttons under a group's watch line."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import actions
from app.modules.ads.constants import ManagedLevel
from app.modules.agent.exceptions import WatchMoved
from app.modules.agent.selectors.launch_watch import Watched, watched_group
from app.modules.audit.models import ActionLog
from core.agent.launch_watch import Move, moved_budget

ACTS: frozenset[str] = frozenset(
    {"budget_up", "budget_down", "pause", "delete", "resume"}
)


def act_on_watch(
    db: Session, *, user: User, adset_id: str, move: str, now: datetime
) -> ActionLog:
    """Carry out one advised move on a group, if it is still advised. Caller commits."""
    row = watched_group(db, owner=user, adset_id=adset_id, now=now)
    if row is None or move not in ACTS or move not in row.watch.moves:
        raise WatchMoved
    if move in ("budget_up", "budget_down"):
        return _budget(db, user=user, row=row, move=move)  # type: ignore[arg-type]
    if move in ("pause", "resume"):
        kind = actions.Pause if move == "pause" else actions.Resume
        ask = kind(level=ManagedLevel.ADSET, external_id=adset_id)
        return actions.request(db, user=user, ask=ask)
    return _delete(db, user=user, row=row)


def _budget(db: Session, *, user: User, row: Watched, move: Move) -> ActionLog:
    if not row.daily_budget_minor:
        raise WatchMoved
    return actions.request(
        db,
        user=user,
        ask=actions.Budget(
            level=ManagedLevel.ADSET,
            external_id=row.adset_id,
            daily_budget_minor=moved_budget(
                budget_minor=row.daily_budget_minor,
                move=move,
                step_pct=row.watch.step_pct,
            ),
        ),
    )


def _delete(db: Session, *, user: User, row: Watched) -> ActionLog:
    if row.delete_level == ManagedLevel.ADSET:
        ask = actions.Delete(level=ManagedLevel.ADSET, external_id=row.adset_id)
    else:
        ask = actions.Delete(level=ManagedLevel.CAMPAIGN, external_id=row.campaign_id)
    return actions.request(db, user=user, ask=ask)


__all__ = ["ACTS", "act_on_watch"]
