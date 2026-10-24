"""Breakdown rows: the same figures cut by age and gender, placement or region."""

from datetime import date
from typing import Any

from adskit import MinorUnits
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import BREAKDOWN_LEVEL, EVERY_ACCOUNT, BreakdownKind
from app.modules.metrics.models import MetricsBreakdown
from app.modules.metrics.selectors.facts import EVERYTHING, Account, Scope
from core.metrics import (
    MIN_SEGMENT_LEADS,
    EngagementFigures,
    SegmentComparison,
    SegmentFigures,
    compare_segments,
)

B = MetricsBreakdown


def breakdown_where(
    db: Session,
    *,
    owner: User,
    kind: str = BreakdownKind.AGE_GENDER,
    level: str = BREAKDOWN_LEVEL,
    account: Account = None,
) -> list[ColumnElement[bool]]:
    from app.modules.integrations.selectors import active_ad_account

    where = [B.owner_id == owner.id, B.breakdown_kind == str(kind), B.level == str(level)]
    if account is EVERY_ACCOUNT:
        return where
    chosen = account if account is not None else active_ad_account(db, owner=owner)
    if chosen is not None:
        where.append(B.ad_account_id == chosen.id)  # type: ignore[union-attr]
    return where


def oldest_breakdown_date(
    db: Session,
    *,
    owner: User,
    kind: str = BreakdownKind.AGE_GENDER,
    level: str = BREAKDOWN_LEVEL,
    account: Account = None,
) -> date | None:
    return db.scalar(
        select(func.min(B.date)).where(
            *breakdown_where(db, owner=owner, kind=kind, level=level, account=account)
        )
    )


def newest_breakdown_date(
    db: Session,
    *,
    owner: User,
    kind: str = BreakdownKind.AGE_GENDER,
    level: str = BREAKDOWN_LEVEL,
    account: AdAccount | None = None,
) -> date | None:
    return db.scalar(
        select(func.max(B.date)).where(
            *breakdown_where(db, owner=owner, kind=kind, level=level, account=account)
        )
    )


def _window(
    db: Session, *, owner: User, kind: str, level: str, account: Account, since: date, until: date
) -> list[ColumnElement[bool]]:
    return [
        *breakdown_where(db, owner=owner, kind=kind, level=level, account=account),
        B.date >= since,
        B.date <= until,
    ]


def segment_costs(
    db: Session,
    *,
    owner: User,
    external_id: str = "",
    since: date,
    until: date,
    kind: str = BreakdownKind.AGE_GENDER,
    level: str = BREAKDOWN_LEVEL,
    min_leads: int = MIN_SEGMENT_LEADS,
    account: Account = None,
    scope: Scope = EVERYTHING,
) -> SegmentComparison:
    where = _window(
        db, owner=owner, kind=kind, level=level, account=account, since=since, until=until
    )
    if external_id:
        where.append(B.external_id == external_id)
    rows = db.execute(
        select(
            B.breakdown_value,
            func.coalesce(func.sum(B.spend_minor), 0),
            func.coalesce(func.sum(B.impressions), 0),
            func.coalesce(func.sum(B.clicks), 0),
            func.coalesce(func.sum(B.leads_reported), 0),
        )
        .where(*where, scope(B))
        .group_by(B.breakdown_value)
    )
    return compare_segments(
        [
            SegmentFigures(
                segment=value,
                spend_minor=MinorUnits(int(spend)),
                impressions=int(shown),
                clicks=int(clicks),
                leads_reported=int(leads),
            )
            for value, spend, shown, clicks, leads in rows
        ],
        min_leads=min_leads,
    )


def _ranked(
    db: Session, column: Any, *, limit: int, where: list[ColumnElement[bool]]
) -> list[tuple[str, int]]:
    total = func.sum(column)
    query = (
        select(B.breakdown_value, total)
        .where(*where)
        .group_by(B.breakdown_value)
        .having(total > 0)
        .order_by(total.desc(), B.breakdown_value)
    )
    if limit:
        query = query.limit(limit)
    return [(value, int(count)) for value, count in db.execute(query)]


def segment_leads(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    kind: str = BreakdownKind.REGION,
    limit: int = 0,
    level: str = BREAKDOWN_LEVEL,
    account: Account = None,
    scope: Scope = EVERYTHING,
) -> list[tuple[str, int]]:
    where = _window(
        db, owner=owner, kind=kind, level=level, account=account, since=since, until=until
    )
    return _ranked(db, B.leads_reported, limit=limit, where=[*where, scope(B)])


def segment_showing(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    kind: str = BreakdownKind.REGION,
    limit: int = 0,
    level: str = BREAKDOWN_LEVEL,
    account: Account = None,
    scope: Scope = EVERYTHING,
) -> list[tuple[str, int]]:
    where = _window(
        db, owner=owner, kind=kind, level=level, account=account, since=since, until=until
    )
    return _ranked(db, B.impressions, limit=limit, where=[*where, scope(B)])


def segment_engagement(row: MetricsBreakdown) -> EngagementFigures:
    return EngagementFigures(
        impressions=row.impressions, reach=row.reach, clicks=row.clicks, spend_minor=row.spend_minor
    )


def segment_spread(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    kind: str = BreakdownKind.REGION,
    level: str = BREAKDOWN_LEVEL,
    account: Account = None,
    scope: Scope = EVERYTHING,
) -> list[tuple[str, str, int, int]]:
    where = _window(
        db, owner=owner, kind=kind, level=level, account=account, since=since, until=until
    )
    rows = db.execute(
        select(
            B.campaign_external_id,
            B.breakdown_value,
            func.coalesce(func.sum(B.spend_minor), 0),
            func.coalesce(func.sum(B.impressions), 0),
        )
        .where(*where, scope(B))
        .group_by(B.campaign_external_id, B.breakdown_value)
    )
    return [(campaign, value, int(spend), int(shown)) for campaign, value, spend, shown in rows]
