"""The groups the agent stopped by itself, as watch lines with a button."""

from collections.abc import Collection
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery, ManagedLevel
from app.modules.ads.models import AdSet
from app.modules.agent.constants import AUTO_STOP_MARK, STOPPED_SHOWN_DAYS
from app.modules.agent.selectors.same_day import kind_of
from app.modules.agent.selectors.watched import Watched
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount
from core.agent.launch_watch import Watch

_SWITCHES = (ActionType.PAUSE, ActionType.RESUME)


def _newest(
    db: Session, *, owner: User, adset_ids: Collection[str], actions: tuple[str, ...]
) -> list[ActionLog]:
    return list(
        db.scalars(
            select(ActionLog)
            .where(
                ActionLog.owner_id == owner.id,
                ActionLog.action.in_([str(action) for action in actions]),
                ActionLog.target_level == ManagedLevel.ADSET,
                ActionLog.target_external_id.in_(list(adset_ids)),
                ActionLog.status != ActionStatus.FAILED,
            )
            .order_by(ActionLog.created_at.desc())
        )
    )


def last_stops(
    db: Session, *, owner: User, adset_ids: Collection[str]
) -> dict[str, ActionLog]:
    """Each group's newest stop the agent made by itself, landed or on its way."""
    found: dict[str, ActionLog] = {}
    if not adset_ids:
        return found
    for row in _newest(
        db, owner=owner, adset_ids=adset_ids, actions=(ActionType.PAUSE,)
    ):
        if AUTO_STOP_MARK in (row.request_payload or {}):
            found.setdefault(row.target_external_id, row)
    return found


def stopped_rows(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    born: dict[str, datetime],
    ours: Collection[str],
    now: datetime,
) -> list[Watched]:
    """A line for every group still stopped by the agent's own stop."""
    groups = {
        row.external_id: row
        for row in db.scalars(
            select(AdSet).where(
                AdSet.owner_id == owner.id,
                AdSet.external_id.in_(list(born)),
                AdSet.delivery == Delivery.PAUSED,
            )
        )
    }
    if not groups:
        return []
    latest: dict[str, ActionLog] = {}
    for row in _newest(db, owner=owner, adset_ids=groups, actions=_SWITCHES):
        latest.setdefault(row.target_external_id, row)
    since = now - timedelta(days=STOPPED_SHOWN_DAYS)
    found: list[Watched] = []
    for adset_id, row in groups.items():
        log = latest.get(adset_id)
        if log is None or AUTO_STOP_MARK not in (log.request_payload or {}):
            continue
        if log.status != ActionStatus.APPLIED or log.created_at < since:
            continue
        found.append(
            _stopped(
                row=row,
                log=log,
                account=account,
                born=born[adset_id],
                ours=ours,
                now=now,
            )
        )
    return found


def _stopped(
    *,
    row: AdSet,
    log: ActionLog,
    account: AdAccount,
    born: datetime,
    ours: Collection[str],
    now: datetime,
) -> Watched:
    mark = log.request_payload[AUTO_STOP_MARK]
    campaign_id = row.campaign.external_id if row.campaign_id else ""
    return Watched(
        adset_id=row.external_id,
        name=row.name or row.external_id,
        campaign_id=campaign_id,
        delete_level=ManagedLevel.ADSET
        if campaign_id in ours
        else ManagedLevel.CAMPAIGN,
        currency=account.currency,
        provider=account.provider,
        hours=int((now - born).total_seconds() // 3600),
        spend_minor=mark.get("spent_since_minor", 0),
        results=0,
        kind=kind_of(row.optimization_goal_raw, row.promoted_object_raw),
        daily_budget_minor=mark.get("budget_minor") or None,
        in_review=False,
        watch=Watch(
            stage="stopped", moves=("resume",), advised="resume", tag=str(log.id)
        ),
    )


__all__ = ["last_stops", "stopped_rows"]
