from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount
from app.modules.leads.selectors import counts_by_city, counts_by_hour
from app.modules.metrics.constants import TOP_SOURCES, AnyAccount, BreakdownKind
from app.modules.metrics.selectors.facts import EVERYTHING, Scope
from app.modules.metrics.selectors.segments import segment_leads, segment_showing
from app.modules.metrics.selectors.shapes import SourceBar
from core.metrics import share

CITY_FROM_LEADS: Final = "leads"
CITY_FROM_PROVIDER: Final = "provider"
CITY_FROM_SHOWING: Final = "showing"


def city_bars(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    tzinfo: ZoneInfo,
    account: AdAccount | AnyAccount | None = None,
    scope: Scope = EVERYTHING,
) -> tuple[tuple[SourceBar, ...], str]:
    from app.modules.leads.models import Lead

    ours = counts_by_city(
        db,
        owner=owner,
        since=_start(since, tzinfo),
        until=_start(until + timedelta(days=1), tzinfo),
        limit=0,
        scope=scope(Lead),
    )
    if ours:
        return (bars(ours), CITY_FROM_LEADS)
    theirs = segment_leads(
        db,
        owner=owner,
        since=since,
        until=until,
        kind=BreakdownKind.REGION,
        account=account,
        scope=scope,
    )
    if theirs:
        return (bars(theirs), CITY_FROM_PROVIDER)
    shown = segment_showing(
        db,
        owner=owner,
        since=since,
        until=until,
        kind=BreakdownKind.REGION,
        account=account,
        scope=scope,
    )
    return (bars(shown), CITY_FROM_SHOWING) if shown else ((), "")


def hour_bars(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    tzinfo: ZoneInfo,
    scope: Scope = EVERYTHING,
) -> tuple[SourceBar, ...]:
    from app.modules.leads.models import Lead

    counts = counts_by_hour(
        db,
        owner=owner,
        since=_start(since, tzinfo),
        until=_start(until + timedelta(days=1), tzinfo),
        tzinfo=tzinfo,
        scope=scope(Lead),
    )
    busiest = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return bars([(f"{hour:02d}:00", count) for hour, count in busiest])


def bars(rows: list[tuple[str, int]]) -> tuple[SourceBar, ...]:
    whole = sum((count for _label, count in rows))
    drawn = rows[:TOP_SOURCES]
    top = max((count for _label, count in drawn), default=0)
    return tuple(
        (
            SourceBar(
                label=label,
                share_pct=share(part=count, whole=top),
                leads=count,
                total_pct=share(part=count, whole=whole),
            )
            for label, count in drawn
        )
    )


def _start(day: date, tzinfo: ZoneInfo) -> datetime:
    return datetime.combine(day, datetime.min.time()).replace(tzinfo=tzinfo)


__all__ = [
    "CITY_FROM_LEADS",
    "CITY_FROM_PROVIDER",
    "CITY_FROM_SHOWING",
    "bars",
    "city_bars",
    "hour_bars",
]
