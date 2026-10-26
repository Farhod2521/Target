"""How often one person saw each group over seven days - the one frequency."""

from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily, PeopleCount
from app.modules.metrics.selectors.facts import cabinet_where
from core.agent.frequency import Reading

DAYS = 7


def week_range(
    db: Session, *, owner: User, account: AdAccount
) -> tuple[date, date] | None:
    """The seven days ending the day before the newest one stored, or none."""
    rows = db.execute(
        select(PeopleCount.since, PeopleCount.until)
        .where(
            PeopleCount.owner_id == owner.id,
            PeopleCount.ad_account_id == account.id,
            PeopleCount.level == MetricLevel.ADSET,
        )
        .distinct()
        .order_by(PeopleCount.until.desc(), PeopleCount.since)
    ).all()
    weeks = [
        (since, until) for since, until in rows if (until - since).days == DAYS - 1
    ]
    if not weeks:
        return None
    newest = weeks[0][1]
    finished = [week for week in weeks if week[1] == newest - timedelta(days=1)]
    return finished[0] if finished else weeks[0]


def week_readings(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    adset_ids: Iterable[str],
    before: bool = False,
) -> dict[str, Reading]:
    """``{group: its seven days}``, or the seven before them with ``before``."""
    ids = list(adset_ids)
    window = week_range(db, owner=owner, account=account) if ids else None
    if window is None:
        return {}
    since, until = window
    if before:
        since, until = since - timedelta(days=DAYS), since - timedelta(days=1)
    reach = dict(
        db.execute(
            select(PeopleCount.external_id, PeopleCount.reach).where(
                PeopleCount.owner_id == owner.id,
                PeopleCount.ad_account_id == account.id,
                PeopleCount.level == MetricLevel.ADSET,
                PeopleCount.external_id.in_(ids),
                PeopleCount.since == since,
                PeopleCount.until == until,
            )
        ).all()
    )
    if not reach:
        return {}
    m = MetricsDaily
    sums = {
        row.adset_external_id: row
        for row in db.execute(
            select(
                m.adset_external_id,
                func.sum(m.impressions).label("shown"),
                func.sum(m.spend_minor).label("spent"),
            )
            .where(
                *cabinet_where(db, owner=owner, account=account),
                m.adset_external_id.in_(list(reach)),
                m.date >= since,
                m.date <= until,
            )
            .group_by(m.adset_external_id)
        )
    }
    return {
        adset_id: Reading(
            adset_id=adset_id,
            impressions=int(sums[adset_id].shown or 0),
            reach=int(people or 0),
            spend_minor=int(sums[adset_id].spent or 0),
        )
        for adset_id, people in reach.items()
        if adset_id in sums
    }


__all__ = ["DAYS", "week_range", "week_readings"]
