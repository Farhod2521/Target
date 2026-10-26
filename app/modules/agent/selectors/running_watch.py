"""A running group's finished days, as :mod:`core.agent.running_watch` reads them."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import AdSet
from app.modules.agent.selectors.same_day import RESULT_COLUMNS, group_usuals, kind_of
from app.modules.agent.selectors.window import end_of, start_of, yesterday
from app.modules.integrations.models import AdAccount
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where
from core.agent.running_watch import BEFORE_DAYS, RECENT_DAYS, Running, Tally
from core.agent.usual import TREND_DAYS
from core.metrics import counted_leads, heard_leads, measured

READ_DAYS = RECENT_DAYS + BEFORE_DAYS
EVER = datetime(2000, 1, 1, tzinfo=UTC)


@dataclass(slots=True)
class _Day:
    spend_minor: int = 0
    results: int = 0
    impressions: int = 0
    link_clicks: int = 0


@dataclass(slots=True)
class _Days:
    """One group's finished days, oldest first, and the first it could spend."""

    days: list[tuple[date, _Day]] = field(default_factory=list)
    born: date | None = None


def running_facts(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    groups: list[AdSet],
    born: dict[str, datetime],
    now: datetime,
) -> dict[str, Running]:
    """``{group id: its finished days, as the running watch reads them}``."""
    from app.modules.leads.selectors import adset_days

    if not groups:
        return {}
    tzinfo = account.tzinfo()
    last = yesterday(tzinfo=tzinfo, now=now)
    first = last - timedelta(days=READ_DAYS - 1)
    spent = _spent(
        db, owner=owner, account=account, groups=groups, since=first, until=last
    )
    ours = adset_days(
        db,
        owner=owner,
        since=start_of(first, tzinfo),
        until=end_of(last, tzinfo),
        tzinfo=tzinfo,
    )
    ids = [row.external_id for row in groups]
    usual = group_usuals(db, owner=owner, account=account, adset_ids=ids)
    ever = _results_ever(db, owner=owner, account=account, groups=groups, now=now)
    fresh = account.synced_at is not None and account.synced_at >= end_of(last, tzinfo)
    found: dict[str, Running] = {}
    for row in groups:
        kind = kind_of(row.optimization_goal_raw, row.promoted_object_raw)
        own_born = born[row.external_id].astimezone(tzinfo).date()
        days = _days_of(
            key=row.external_id,
            kind=kind,
            first=max(first, own_born),
            last=last,
            spent=spent,
            ours=ours,
        )
        days.born = own_born
        found[row.external_id] = _running(
            days,
            median=usual(row.external_id, kind),
            last=last,
            spell=ever.get(row.external_id, 0),
            fresh=fresh,
        )
    return found


def _results_ever(
    db: Session, *, owner: User, account: AdAccount, groups: list[AdSet], now: datetime
) -> dict[str, int]:
    """``{group id: every result it has brought}``, ours or the provider's."""
    from app.modules.leads.selectors import counts_by_adset

    m = MetricsDaily
    columns = sorted(set(RESULT_COLUMNS.values()))
    rows = db.execute(
        select(
            m.adset_external_id,
            *(func.sum(getattr(m, column)).label(column) for column in columns),
        )
        .where(
            *cabinet_where(db, owner=owner, account=account),
            m.adset_external_id.in_([row.external_id for row in groups]),
        )
        .group_by(m.adset_external_id)
    ).mappings()
    ours = counts_by_adset(db, owner=owner, since=EVER, until=now)
    found: dict[str, int] = {}
    for row in rows:
        key = row["adset_external_id"]
        theirs = sum(int(row[column] or 0) for column in columns)
        found[key] = heard_leads(ours=ours.get(key, (0, 0))[0], reported=theirs)
    return found


def _spent(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    groups: list[AdSet],
    since: date,
    until: date,
) -> dict[tuple[str, date], dict[str, int]]:
    m = MetricsDaily
    columns = (
        "spend_minor",
        "impressions",
        "inline_link_clicks",
        *sorted(set(RESULT_COLUMNS.values())),
    )
    rows = db.execute(
        select(
            m.adset_external_id,
            m.date,
            *(func.sum(getattr(m, column)).label(column) for column in columns),
        )
        .where(
            *cabinet_where(db, owner=owner, account=account),
            m.adset_external_id.in_([row.external_id for row in groups]),
            m.date >= since,
            m.date <= until,
        )
        .group_by(m.adset_external_id, m.date)
    ).mappings()
    return {
        (row["adset_external_id"], row["date"]): {
            column: int(row[column] or 0) for column in columns
        }
        for row in rows
    }


def _days_of(
    *,
    key: str,
    kind: str,
    first: date,
    last: date,
    spent: dict[tuple[str, date], dict[str, int]],
    ours: dict[tuple[str, date], int],
) -> _Days:
    column = RESULT_COLUMNS.get(kind)
    found = _Days()
    day = first
    while day <= last:
        sums = spent.get((key, day), {})
        results = sums.get(column, 0) if column else 0
        if kind == "lead":
            results = counted_leads(
                ours=ours.get((key, day), 0),
                reported=results,
                measured=measured(
                    spend_minor=sums.get("spend_minor", 0),
                    impressions=sums.get("impressions", 0),
                    reported=results,
                ),
            )
        found.days.append(
            (
                day,
                _Day(
                    spend_minor=sums.get("spend_minor", 0),
                    results=results,
                    impressions=sums.get("impressions", 0),
                    link_clicks=sums.get("inline_link_clicks", 0),
                ),
            )
        )
        day += timedelta(days=1)
    return found


def _running(
    days: _Days, *, median: int | None, last: date, spell: int, fresh: bool
) -> Running:
    dry = _dry(days)
    idle_days, idle_since, spent_before = _idle(days)
    if not fresh:
        idle_days, idle_since = 0, None
    split = last - timedelta(days=RECENT_DAYS - 1)
    year, week, _weekday = last.isocalendar()
    before = [when for when, _day in days.days if when < split]
    return Running(
        dry_days=dry.days,
        dry_spend_minor=dry.spend_minor,
        dry_impressions=dry.impressions,
        dry_link_clicks=dry.link_clicks,
        spell=spell,
        expected_cost_minor=median,
        recent=_tally(days, since=split),
        before=_tally(days, until=split),
        idle_days=idle_days,
        idle_since=idle_since,
        spent_before=spent_before,
        week=f"{year}-W{week:02d}",
        before_days=len(before),
        last=_tally(days, since=last - timedelta(days=TREND_DAYS - 1)),
        usual_cost_minor=median,
    )


@dataclass(frozen=True, slots=True)
class _Spell:
    days: int = 0
    spend_minor: int = 0
    impressions: int = 0
    link_clicks: int = 0


def _dry(days: _Days) -> _Spell:
    """Days since the last result, and what they cost and bought."""
    picked: list[_Day] = []
    for _when, day in reversed(days.days):
        if day.results:
            break
        picked.append(day)
    return _Spell(
        days=len(picked),
        spend_minor=sum(day.spend_minor for day in picked),
        impressions=sum(day.impressions for day in picked),
        link_clicks=sum(day.link_clicks for day in picked),
    )


def _idle(days: _Days) -> tuple[int, date | None, bool]:
    """Days in a row with nothing spent, the first of them, and whether the
    day before them spent."""
    count = 0
    since: date | None = None
    for when, day in reversed(days.days):
        if day.spend_minor:
            return count, since, count > 0
        count += 1
        since = when
    return count, since, False


def _tally(
    days: _Days, *, since: date | None = None, until: date | None = None
) -> Tally:
    picked = [
        day
        for when, day in days.days
        if (since is None or when >= since) and (until is None or when < until)
    ]
    return Tally(
        spend_minor=sum(day.spend_minor for day in picked),
        results=sum(day.results for day in picked),
    )


__all__ = ["READ_DAYS", "running_facts"]
