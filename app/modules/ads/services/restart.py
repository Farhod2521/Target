"""A launch's switch-on that never reached Meta, tried again.

The auto-start writes «started» once the resumes are queued, before Meta has
answered. A resume that then failed for a passing reason (Meta busy, no
worker in time) left the advert paused at Meta while the cabinet said it
runs, and a launch whose switch-on waited past its window («Meta hozir javob
bermadi») stayed paused for good. Nothing asked again.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.modules.ads.constants import ACTION_STALE_MINUTES, LaunchStatus
from app.modules.ads.models import CampaignLaunch, DeliveryStop
from app.modules.ads.selectors.launched import launched_targets
from app.modules.ads.services.creation import LATE_NOTE, switch_on
from app.modules.audit.constants import ActionStatus, ActionType, ActorType
from app.modules.audit.models import ActionLog

# Refusals that say nothing about the advert: the same resume may pass later.
PASSING_CODES: Final = frozenset({"temporary", "stalled"})
RESTART_FOR: Final = timedelta(hours=24)
# Past the stalled sweep, so a resume no worker took is already closed.
SETTLED_AFTER: Final = timedelta(minutes=ACTION_STALE_MINUTES + 5)
MAX_RESTARTS: Final = 3
RESTARTS: Final = "restarts"


def restart_launches(db: Session, *, now: datetime) -> int:
    """Switch on again what the last day's launches left off. Returns how many."""
    launches = db.scalars(
        select(CampaignLaunch).where(
            CampaignLaunch.status == str(LaunchStatus.CREATED),
            CampaignLaunch.finished_at >= now - RESTART_FOR,
            CampaignLaunch.finished_at < now - SETTLED_AFTER,
        )
    ).all()
    started = 0
    for launch in launches:
        targets = launched_targets(launch=launch)
        if not targets or not restart_due(db, launch=launch, targets=targets):
            continue
        # Counted before the try: a refusal rolls the session back.
        launch.draft = {**(launch.draft or {}), RESTARTS: restarts(launch) + 1}
        db.commit()
        if switch_on(db, launch=launch, targets=targets) == "started":
            started += 1
    return started


def restarts(launch: CampaignLaunch) -> int:
    found = (launch.draft or {}).get(RESTARTS)
    return found if isinstance(found, int) else 0


def restart_due(
    db: Session, *, launch: CampaignLaunch, targets: Sequence[tuple[str, str]]
) -> bool:
    """Left off by the switch-on itself, and by nobody else."""
    if restarts(launch) >= MAX_RESTARTS:
        return False
    ids = [ref for _level, ref in targets]
    if _someone_stepped_in(db, launch=launch, ids=ids):
        return False
    if launch.delivery_note == LATE_NOTE:
        return True
    if launch.delivery_started_at is None:
        return False
    return _a_resume_fell_through(db, launch=launch, ids=ids)


def _someone_stepped_in(db: Session, *, launch: CampaignLaunch, ids: list[str]) -> bool:
    """The owner, the agent or a lapse touched it, or Ads Manager stopped it."""
    touched = db.scalar(
        select(
            exists().where(
                ActionLog.owner_id == launch.owner_id,
                ActionLog.target_external_id.in_(ids),
                ActionLog.created_at > launch.finished_at,
                (ActionLog.actor_type != str(ActorType.SYSTEM))
                | (ActionLog.action != str(ActionType.RESUME)),
            )
        )
    )
    stopped = db.scalar(
        select(
            exists().where(
                DeliveryStop.owner_id == launch.owner_id,
                DeliveryStop.campaign_external_id.in_(ids),
                DeliveryStop.cleared_at.is_(None),
            )
        )
    )
    return bool(touched or stopped)


def _a_resume_fell_through(
    db: Session, *, launch: CampaignLaunch, ids: list[str]
) -> bool:
    """The system's last resume of some object failed for a passing reason."""
    logs = db.scalars(
        select(ActionLog)
        .where(
            ActionLog.owner_id == launch.owner_id,
            ActionLog.target_external_id.in_(ids),
            ActionLog.actor_type == str(ActorType.SYSTEM),
            ActionLog.action == str(ActionType.RESUME),
        )
        .order_by(ActionLog.created_at.desc())
    ).all()
    last: dict[str, ActionLog] = {}
    for log in logs:
        last.setdefault(log.target_external_id, log)
    return any(
        log.status == str(ActionStatus.FAILED) and log.error_code in PASSING_CODES
        for log in last.values()
    )


__all__ = ["MAX_RESTARTS", "restart_due", "restart_launches", "restarts"]
