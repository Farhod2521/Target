"""The daily figure rows a cabinet reads, and the dates and stamps around them.

A ``Scope`` here is a function of the model it narrows: the same campaign
filter has to apply to MetricsDaily, MetricsBreakdown and Lead, which share
the column names - Django passed one ``Q`` to all three.
"""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from adskit import MinorUnits
from metaads import PROVIDER as META
from sqlalchemy import ColumnElement, func, or_, select, true
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import (
    AUTO_REFRESH_COOLING_MINUTES,
    EVERY_ACCOUNT,
    INSIGHT_LEVELS,
    STALE_HOURS,
    AnyAccount,
    MetricLevel,
    Ranking,
)
from app.modules.metrics.models import MetricsDaily, PeopleCount
from core.metrics import DayFigures

Scope = Callable[[Any], ColumnElement[bool]]


def EVERYTHING(_model: Any) -> ColumnElement[bool]:
    return true()


def campaigns_scope(campaign_ids: Collection[str]) -> Scope:
    ids = list(campaign_ids)
    return lambda model: model.campaign_external_id.in_(ids)


Account = AdAccount | AnyAccount | None


def _observed_account() -> Any:
    return select(AdAccount.id).where(
        AdAccount.is_active.is_(False), AdAccount.leads_seen_at.is_not(None)
    )


def cabinet_where(
    db: Session,
    *,
    owner: User,
    level: str | None = MetricLevel.ADSET,
    account: Account = None,
) -> list[ColumnElement[bool]]:
    """The filter for one cabinet's figure rows (the Django ``cabinet_rows``)."""
    from app.modules.integrations.selectors import active_ad_account

    where: list[ColumnElement[bool]] = [MetricsDaily.owner_id == owner.id]
    if level is not None:
        where.append(MetricsDaily.level == str(level))
    if account is EVERY_ACCOUNT:
        where.append(MetricsDaily.provider == META)
        return where
    chosen = account if account is not None else active_ad_account(db, owner=owner)
    if chosen is None:
        return where
    where.append(
        or_(
            MetricsDaily.ad_account_id == chosen.id,  # type: ignore[union-attr]
            MetricsDaily.ad_account_id.is_(None),
            MetricsDaily.ad_account_id.in_(_observed_account()),
        )
    )
    return where


def newest_metrics_date(
    db: Session, *, ad_account: AdAccount, level: str = MetricLevel.ADSET
) -> date | None:
    return db.scalar(
        select(func.max(MetricsDaily.date)).where(
            MetricsDaily.owner_id == ad_account.owner_id,
            MetricsDaily.level == str(level),
            or_(
                MetricsDaily.ad_account_id == ad_account.id,
                MetricsDaily.ad_account_id.is_(None),
            ),
        )
    )


def last_synced_at(
    db: Session, *, owner: User, account: AdAccount | None = None
) -> datetime | None:
    return db.scalar(
        select(func.max(MetricsDaily.synced_at)).where(
            *cabinet_where(db, owner=owner, account=account)
        )
    )


def accounts_synced_at(
    db: Session, *, owner: User, accounts: Sequence[AdAccount]
) -> datetime | None:
    stamps = [
        stamp
        for account in accounts
        if (stamp := last_synced_at(db, owner=owner, account=account)) is not None
    ]
    return min(stamps, default=None)


def _stalest_synced_at(
    db: Session, *, owner: User, account: AdAccount
) -> datetime | None:
    seen = db.scalars(
        select(func.max(MetricsDaily.synced_at))
        .where(
            *cabinet_where(db, owner=owner, level=None, account=account),
            MetricsDaily.level.in_([str(level) for level in INSIGHT_LEVELS]),
        )
        .group_by(MetricsDaily.level)
    )
    return min((stamp for stamp in seen if stamp is not None), default=None)


def accounts_stalest_synced_at(
    db: Session, *, owner: User, accounts: Sequence[AdAccount]
) -> datetime | None:
    stamps = [
        stamp
        for account in accounts
        if (stamp := _stalest_synced_at(db, owner=owner, account=account)) is not None
    ]
    return min(stamps, default=None)


def figures_are_stale(*, synced_at: datetime | None, now: datetime) -> bool:
    if synced_at is None:
        return False
    return now - synced_at > timedelta(hours=STALE_HOURS)


def figures_behind_since(
    db: Session, *, owner: User, accounts: Sequence[AdAccount], now: datetime
) -> datetime | None:
    behind = accounts_stalest_synced_at(db, owner=owner, accounts=accounts)
    if behind is None or now - behind <= timedelta(hours=STALE_HOURS):
        return None
    shown = accounts_synced_at(db, owner=owner, accounts=accounts)
    if shown is None or now - shown > timedelta(hours=STALE_HOURS):
        return None
    return behind


def has_cooled(*, synced_at: datetime | None) -> bool:
    if synced_at is None:
        return True
    return utcnow() - synced_at >= timedelta(minutes=AUTO_REFRESH_COOLING_MINUTES)


# -- sums -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CampaignSums:
    spend_minor: int = 0
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0
    leads_reported: int = 0


@dataclass(frozen=True, slots=True)
class DaySums:
    spend_minor: int = 0
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    leads_reported: int = 0
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0


def _sums() -> list[Any]:
    m = MetricsDaily
    return [
        func.coalesce(func.sum(m.spend_minor), 0).label("spend"),
        func.coalesce(func.sum(m.impressions), 0).label("impressions"),
        func.coalesce(func.sum(m.clicks), 0).label("clicks"),
        func.coalesce(func.sum(m.inline_link_clicks), 0).label("link_clicks"),
        func.coalesce(func.sum(m.results_reported), 0).label("results"),
        func.coalesce(func.sum(m.recallers), 0).label("recallers"),
        func.coalesce(func.sum(m.profile_visits), 0).label("profile_visits"),
        func.coalesce(func.sum(m.leads_reported), 0).label("leads_reported"),
    ]


def facts_by_campaign(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    account: Account = None,
    scope: Scope = EVERYTHING,
) -> dict[str, CampaignSums]:
    rows = db.execute(
        select(MetricsDaily.campaign_external_id, *_sums())
        .where(
            *cabinet_where(db, owner=owner, account=account),
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            scope(MetricsDaily),
            MetricsDaily.campaign_external_id != "",
        )
        .group_by(MetricsDaily.campaign_external_id)
    )
    sums = {
        row.campaign_external_id: CampaignSums(
            spend_minor=int(row.spend),
            impressions=int(row.impressions),
            clicks=int(row.clicks),
            link_clicks=int(row.link_clicks),
            results=int(row.results),
            recallers=int(row.recallers),
            profile_visits=int(row.profile_visits),
            leads_reported=int(row.leads_reported),
        )
        for row in rows
    }
    counted = people_counts(
        db, owner=owner, level=MetricLevel.CAMPAIGN, since=since, until=until, ids=sums
    )
    return {
        key: replace(row, recallers=counted[key].recallers) if key in counted else row
        for key, row in sums.items()
    }


def spend_by_day(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    account: Account = None,
    scope: Scope = EVERYTHING,
) -> dict[date, DaySums]:
    rows = db.execute(
        select(MetricsDaily.date, *_sums())
        .where(
            *cabinet_where(db, owner=owner, account=account),
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            scope(MetricsDaily),
        )
        .group_by(MetricsDaily.date)
    )
    return {
        row.date: DaySums(
            spend_minor=int(row.spend),
            impressions=int(row.impressions),
            clicks=int(row.clicks),
            link_clicks=int(row.link_clicks),
            leads_reported=int(row.leads_reported),
            results=int(row.results),
            recallers=int(row.recallers),
            profile_visits=int(row.profile_visits),
        )
        for row in rows
    }


def daily_facts(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    tzinfo: ZoneInfo,
    account: Account = None,
    scope: Scope = EVERYTHING,
) -> list[DayFigures]:
    from app.modules.leads.models import Lead
    from app.modules.leads.selectors import daily_counts

    spend = spend_by_day(
        db, owner=owner, since=since, until=until, account=account, scope=scope
    )
    leads = daily_counts(
        db,
        owner=owner,
        since=start_of(since, tzinfo),
        until=end_of(until, tzinfo),
        tzinfo=tzinfo,
        scope=scope(Lead),
    )
    return [
        _figures(day=day, spend=spend.get(day), leads=leads.get(day))
        for day in walk(since, until)
    ]


def _figures(
    *, day: date, spend: DaySums | None, leads: tuple[int, int] | None
) -> DayFigures:
    sums = spend or DaySums()
    count, qualified = leads or (0, 0)
    return DayFigures(
        day=day,
        spend_minor=MinorUnits(sums.spend_minor),
        impressions=sums.impressions,
        clicks=sums.clicks,
        link_clicks=sums.link_clicks,
        leads=count,
        qualified=qualified,
        leads_reported=sums.leads_reported,
        results=sums.results,
        recallers=sums.recallers,
        profile_visits=sums.profile_visits,
    )


RANKING_FIELDS: Final = (
    "quality_ranking",
    "engagement_rate_ranking",
    "conversion_rate_ranking",
)
LOW_BANDS: Final = frozenset({Ranking.BELOW_AVERAGE_20, Ranking.BELOW_AVERAGE_10})
RANKING_ROWS: Final = 300


@dataclass(frozen=True, slots=True)
class LowRanking:
    external_id: str
    name: str
    verdict: str


def low_rankings(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    account: AdAccount | None = None,
    hidden_campaigns: Collection[str] = (),
) -> tuple[LowRanking, ...]:
    m = MetricsDaily
    rows = db.execute(
        select(
            m.external_id,
            m.object_name,
            m.quality_ranking,
            m.engagement_rate_ranking,
            m.conversion_rate_ranking,
        )
        .where(
            *cabinet_where(db, owner=owner, level=MetricLevel.AD, account=account),
            m.date >= since,
            m.date <= until,
            m.campaign_external_id.not_in(list(hidden_campaigns)),
            m.quality_ranking != "",
        )
        .order_by(m.date.desc())
        .limit(RANKING_ROWS)
    )
    seen: set[str] = set()
    found: list[LowRanking] = []
    labels = dict(Ranking.choices)
    for row in rows:
        if row.external_id in seen:
            continue
        seen.add(row.external_id)
        verdict = next(
            (
                getattr(row, field)
                for field in RANKING_FIELDS
                if getattr(row, field) in LOW_BANDS
            ),
            "",
        )
        if verdict:
            found.append(
                LowRanking(
                    external_id=row.external_id,
                    name=row.object_name or row.external_id,
                    verdict=str(labels.get(verdict, verdict)),
                )
            )
    return tuple(found)


def walk(since: date, until: date) -> list[date]:
    return [since + timedelta(days=n) for n in range((until - since).days + 1)]


def start_of(day: date, tzinfo: Any) -> datetime:
    return datetime.combine(day, time.min).replace(tzinfo=tzinfo)


def end_of(day: date, tzinfo: Any) -> datetime:
    return datetime.combine(day, time.max).replace(tzinfo=tzinfo)


# -- people (reach and recallers per range) --------------------------------------------


@dataclass(frozen=True, slots=True)
class People:
    reach: int = 0
    recallers: int = 0


def people_counts(
    db: Session,
    *,
    owner: User,
    level: str,
    since: date,
    until: date,
    ids: Collection[str],
) -> dict[str, People]:
    wanted = [one for one in ids if one]
    if not wanted:
        return {}
    rows = db.execute(
        select(PeopleCount.external_id, PeopleCount.reach, PeopleCount.recallers).where(
            PeopleCount.owner_id == owner.id,
            PeopleCount.level == str(level),
            PeopleCount.since == since,
            PeopleCount.until == until,
            PeopleCount.external_id.in_(wanted),
        )
    )
    return {
        external_id: People(reach=reach, recallers=recallers)
        for external_id, reach, recallers in rows
    }


def with_people_counts(
    db: Session,
    sums: dict[str, dict[str, int]],
    *,
    owner: User,
    level: str,
    since: date,
    until: date,
) -> dict[str, dict[str, int]]:
    counted = people_counts(
        db, owner=owner, level=level, since=since, until=until, ids=sums
    )
    out: dict[str, dict[str, int]] = {}
    for key, row in sums.items():
        if key not in counted:
            out[key] = row
            continue
        found = counted[key]
        impressions = row.get("impressions")
        reach = (
            {}
            if impressions is not None and found.reach > impressions
            else {"reach": found.reach}
        )
        out[key] = {**row, "recallers": found.recallers, **reach}
    return out


def people_by_range(
    db: Session, *, owner: User, level: str, external_id: str
) -> dict[tuple[date, date], People]:
    rows = db.execute(
        select(
            PeopleCount.since,
            PeopleCount.until,
            PeopleCount.reach,
            PeopleCount.recallers,
        ).where(
            PeopleCount.owner_id == owner.id,
            PeopleCount.level == str(level),
            PeopleCount.external_id == external_id,
        )
    )
    return {
        (since, until): People(reach=reach, recallers=recallers)
        for since, until, reach, recallers in rows
    }


def people_synced_at(
    db: Session, *, ad_account: AdAccount, until: date
) -> datetime | None:
    return db.scalar(
        select(func.max(PeopleCount.synced_at)).where(
            PeopleCount.owner_id == ad_account.owner_id,
            PeopleCount.ad_account_id == ad_account.id,
            PeopleCount.level == str(MetricLevel.CAMPAIGN),
            PeopleCount.until == until,
        )
    )


# -- spend ------------------------------------------------------------------------------


def has_spent(db: Session, *, owner: User, adset_id: str) -> bool:
    return (
        db.scalar(
            select(MetricsDaily.id)
            .where(
                MetricsDaily.owner_id == owner.id,
                MetricsDaily.level == str(MetricLevel.ADSET),
                MetricsDaily.adset_external_id == adset_id,
                MetricsDaily.spend_minor > 0,
            )
            .limit(1)
        )
        is not None
    )


def campaign_has_run(db: Session, *, owner: User, campaign_id: str) -> bool:
    return (
        db.scalar(
            select(MetricsDaily.id)
            .where(
                MetricsDaily.owner_id == owner.id,
                MetricsDaily.campaign_external_id == campaign_id,
                or_(MetricsDaily.spend_minor > 0, MetricsDaily.impressions > 0),
            )
            .limit(1)
        )
        is not None
    )


def group_leads(
    db: Session,
    *,
    ad_account: AdAccount,
    campaign_ids: Collection[str],
    days: Collection[date],
    synced_since: datetime,
) -> dict[tuple[str, date], int]:
    rows = db.execute(
        select(
            MetricsDaily.campaign_external_id,
            MetricsDaily.date,
            func.sum(MetricsDaily.leads_reported),
        )
        .where(
            MetricsDaily.owner_id == ad_account.owner_id,
            MetricsDaily.ad_account_id == ad_account.id,
            MetricsDaily.level == str(MetricLevel.ADSET),
            MetricsDaily.campaign_external_id.in_(list(campaign_ids)),
            MetricsDaily.date.in_(list(days)),
            MetricsDaily.synced_at >= synced_since,
        )
        .group_by(MetricsDaily.campaign_external_id, MetricsDaily.date)
    )
    return {(campaign, day): int(leads or 0) for campaign, day, leads in rows}


# -- the watched (not ours) accounts ---------------------------------------------------


def watched_groups(db: Session, *, ad_account: AdAccount) -> set[str]:
    from app.modules.ads.models import AdSet, Campaign
    from app.modules.leads.selectors import lead_adset_ids

    mirrored = set(
        db.scalars(
            select(AdSet.external_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == ad_account.owner_id,
                Campaign.ad_account_id == ad_account.id,
            )
        )
    )
    return mirrored | set(lead_adset_ids(db, owner=ad_account.owner))


def watched_campaigns(db: Session, *, ad_account: AdAccount) -> set[str]:
    from app.modules.ads.models import Campaign

    return set(
        db.scalars(
            select(Campaign.external_id).where(
                Campaign.owner_id == ad_account.owner_id,
                Campaign.ad_account_id == ad_account.id,
                Campaign.external_id != "",
            )
        )
    )


def observed_window(
    db: Session, *, ad_account: AdAccount, today: date
) -> tuple[date, date]:
    from app.modules.metrics.constants import BACKFILL_DAYS, OBSERVED_RESTATE_DAYS

    held = db.scalar(
        select(MetricsDaily.id)
        .where(
            MetricsDaily.ad_account_id == ad_account.id,
            MetricsDaily.level == str(MetricLevel.ADSET),
        )
        .limit(1)
    )
    span = OBSERVED_RESTATE_DAYS if held is not None else BACKFILL_DAYS
    return today - timedelta(days=span - 1), today
