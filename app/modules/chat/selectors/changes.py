"""What changed in an account during one week. A closed list, from tables."""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.chat.constants import CHANGES_IN_REPORT
from core.chat.report import Change
from core.metrics import Totals, is_beyond_noise, movement

MOVES_THE_FIGURES: frozenset[str] = frozenset(
    {
        ActionType.PAUSE,
        ActionType.RESUME,
        ActionType.BUDGET_UP,
        ActionType.BUDGET_DOWN,
        ActionType.TARGETING_SWAP,
        ActionType.END_TIME_SET,
        ActionType.SPEND_CAP_SET,
        ActionType.CREATIVE_SWAP,
        ActionType.CREATE_ADSET,
        ActionType.CREATE_AD,
        ActionType.CREATE_CAMPAIGN,
        ActionType.DELETE_CAMPAIGN,
        ActionType.DELETE_ADSET,
        ActionType.DELETE_AD,
    }
)


def week_changes(
    db: Session,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    names: dict[str, str],
    targets: dict[str, str],
    now_spend: dict[str, int],
    before_spend: dict[str, int],
    now: Totals,
    before: Totals,
) -> tuple[Change, ...]:
    """Everything that changed, newest kind first, bounded."""
    found = [
        *_applied(db, owner=owner, since=since, until=until, targets=targets),
        *_lifecycle(names=names, now=now_spend, before=before_spend),
    ]
    return tuple(found[:CHANGES_IN_REPORT])


def _applied(
    db: Session,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    targets: dict[str, str],
) -> list[Change]:
    """Changes that actually reached the provider inside the week."""
    if not targets:
        return []
    rows = db.scalars(
        select(ActionLog)
        .where(
            ActionLog.owner_id == owner.id,
            ActionLog.status == ActionStatus.APPLIED,
            ActionLog.applied_at >= since,
            ActionLog.applied_at <= until,
            ActionLog.action.in_(MOVES_THE_FIGURES),
            ActionLog.target_external_id.in_(list(targets)),
        )
        .order_by(ActionLog.applied_at.desc())
        .limit(CHANGES_IN_REPORT)
    )
    return [
        Change(
            kind="applied",
            what=f"{_action_label(row.action)}: {targets[row.target_external_id]}",
        )
        for row in rows
    ]


def _action_label(action: str) -> str:
    try:
        return str(ActionType(action).label)
    except ValueError:
        return action


def _lifecycle(
    *, names: dict[str, str], now: dict[str, int], before: dict[str, int]
) -> list[Change]:
    """Campaigns that began spending this week, and ones that stopped."""
    started = [key for key in now if now[key] > 0 and before.get(key, 0) == 0]
    stopped = [key for key in before if before[key] > 0 and now.get(key, 0) == 0]
    changes = [
        Change(
            kind="started",
            what="Yangi reklama ishga tushdi: %(name)s" % {"name": names.get(key, key)},
        )
        for key in started
    ]
    changes += [
        Change(
            kind="stopped",
            what="Reklama to'xtadi: %(name)s" % {"name": names.get(key, key)},
        )
        for key in stopped
    ]
    return changes


def _quality(*, now: Totals, before: Totals) -> list[Change]:
    """Whether the share of leads worth having moved, beyond its own error."""
    moved = movement(
        now=now.quality_share, before=before.quality_share, lower_is_better=False
    )
    if moved.direction == "flat" or not is_beyond_noise(
        percent=moved.percent, now=now.leads, before=before.leads
    ):
        return []
    text = (
        "Sifatli murojaatlar ulushi oshdi"
        if moved.is_good
        else "Sifatli murojaatlar ulushi kamaydi"
    )
    return [Change(kind="quality", what=text)]


def active_days(*, spend_by_day: list[int]) -> int:
    """How many days of a week actually spent anything."""
    return sum(1 for amount in spend_by_day if amount > 0)


def week_bounds(*, today: date) -> tuple[date, date]:
    """Monday to Sunday of the last week that finished, in the account's own days."""
    this_monday = today - timedelta(days=today.weekday())
    end = this_monday - timedelta(days=1)
    return end - timedelta(days=6), end


__all__ = ["MOVES_THE_FIGURES", "active_days", "week_bounds", "week_changes"]
