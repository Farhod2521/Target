"""Each row's figures for the expert table, read once per level and account.

Nothing here divides: it reads the counts the catalogue's formulas take -
the network's daily sums, people over the whole range, the last day's
rankings, and our own leads, qualified leads and sales from the CRM.
"""

from collections.abc import Collection
from datetime import date
from typing import Any, Final

from adskit import MinorUnits
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.crm.quality import crm_account_ids
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.ranges import Range
from app.modules.metrics.selectors.facts import (
    newest_metrics_date,
    people_counts,
)
from app.modules.metrics.selectors.panel import end_of, start_of
from core.metrics.catalogue import Figures

M = MetricsDaily

# Which rows answer for each level, and the column naming their object. A
# campaign is its ad sets' rows, as everywhere else in the cabinet.
READS: Final[dict[str, tuple[str, Any]]] = {
    MetricLevel.CAMPAIGN: (MetricLevel.ADSET, M.campaign_external_id),
    MetricLevel.ADSET: (MetricLevel.ADSET, M.adset_external_id),
    MetricLevel.AD: (MetricLevel.AD, M.external_id),
}

# Figures field and the daily column summed into it.
SUMMED: Final[dict[str, Any]] = {
    "spend_minor": M.spend_minor,
    "impressions": M.impressions,
    "link_clicks": M.inline_link_clicks,
    "landing_page_views": M.landing_page_views,
    "results": M.results_reported,
    "leads_reported": M.leads_reported,
    "recallers": M.recallers,
    "profile_visits": M.profile_visits,
    "purchases_site": M.purchases_site,
    "purchase_value_site_minor": M.purchase_value_site_minor,
    "video_plays": M.video_plays,
    "video_views_3s": M.video_views_3s,
    "video_thruplays": M.video_thruplays,
}
RANKINGS: Final = (
    "quality_ranking",
    "engagement_rate_ranking",
    "conversion_rate_ranking",
)


def _sums(
    db: Session,
    *,
    account: AdAccount,
    level: str,
    ids: Collection[str],
    date_range: Range,
) -> dict[str, dict[str, int]]:
    rows_of, key = READS[level]
    found = db.execute(
        select(
            key,
            *[
                func.coalesce(func.sum(col), 0).label(name)
                for name, col in SUMMED.items()
            ],
        )
        .where(
            M.owner_id == account.owner_id,
            M.ad_account_id == account.id,
            M.level == str(rows_of),
            M.date >= date_range.since,
            M.date <= date_range.until,
            key.in_(list(ids)),
        )
        .group_by(key)
    )
    return {row[0]: {name: int(row._mapping[name]) for name in SUMMED} for row in found}


def _last_rankings(
    db: Session, *, account: AdAccount, ids: Collection[str], date_range: Range
) -> dict[str, dict[str, str]]:
    """Each ad's verdicts on the last day of the range Meta gave any."""
    rows = db.execute(
        select(M.external_id, *[getattr(M, name) for name in RANKINGS])
        .where(
            M.owner_id == account.owner_id,
            M.ad_account_id == account.id,
            M.level == str(MetricLevel.AD),
            M.date >= date_range.since,
            M.date <= date_range.until,
            M.external_id.in_(list(ids)),
            M.quality_ranking != "",
        )
        .order_by(M.external_id, M.date.desc())
        .distinct(M.external_id)
    )
    return {row[0]: dict(zip(RANKINGS, row[1:], strict=True)) for row in rows}


def _leads(
    db: Session, *, owner: User, level: str, since: Any, until: Any
) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    from app.modules.leads.selectors import (
        counts_by_ad,
        counts_by_adset,
        counts_by_campaign,
        sales_by,
    )

    by_level: dict[str, Any] = {
        MetricLevel.CAMPAIGN: counts_by_campaign,
        MetricLevel.ADSET: counts_by_adset,
        MetricLevel.AD: counts_by_ad,
    }
    counts = by_level[str(level)](db, owner=owner, since=since, until=until)
    return counts, sales_by(db, owner=owner, level=str(level), since=since, until=until)


def figures_by(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    level: str,
    ids: Collection[str],
    date_range: Range,
) -> dict[str, Figures]:
    """Every asked row's :class:`Figures`; a row with nothing has nought."""
    wanted = [one for one in ids if one]
    if not wanted:
        return {}
    zone = account.tzinfo()
    since, until = start_of(date_range.since, zone), end_of(date_range.until, zone)
    sums = _sums(db, account=account, level=level, ids=wanted, date_range=date_range)
    people = people_counts(
        db,
        owner=owner,
        level=str(level),
        since=date_range.since,
        until=date_range.until,
        ids=wanted,
    )
    rankings = (
        _last_rankings(db, account=account, ids=wanted, date_range=date_range)
        if level == MetricLevel.AD
        else {}
    )
    counts, sold = _leads(db, owner=owner, level=level, since=since, until=until)
    read = newest_metrics_date(db, ad_account=account) is not None
    crm = account.id in crm_account_ids(db, owner_id=owner.id)
    found: dict[str, Figures] = {}
    for one in wanted:
        summed = sums.get(one, {})
        counted = people.get(one)
        leads, qualified = counts.get(one, (0, 0))
        shown = summed.get("impressions", 0)
        given: dict[str, Any] = {name: summed.get(name, 0) for name in SUMMED}
        given.update(rankings.get(one, {}))
        given["spend_minor"] = MinorUnits(given["spend_minor"])
        given["purchase_value_site_minor"] = MinorUnits(
            given["purchase_value_site_minor"]
        )
        found[one] = Figures(
            **given,
            leads_ours=leads,
            qualified=qualified,
            purchases_crm=sold.get(one, 0),
            reach=_people(counted.reach if counted else None, shown=shown),
            unique_link_clicks=_people(
                counted.unique_link_clicks if counted else None, shown=shown
            ),
            read=read,
            crm=crm,
        )
    return found


def _people(count: int | None, *, shown: int) -> int | None:
    """Nought where nothing was shown; ``None`` where Meta was not asked, or
    answered more people than showings, which is a range it did not count."""
    if not shown:
        return 0
    if count is None or count > shown:
        return None
    return count


def last_read_on(db: Session, *, accounts: Collection[AdAccount]) -> Any:
    """When the newest of these accounts' figures was read."""
    ids = [account.id for account in accounts]
    if not ids:
        return None
    return db.scalar(select(func.max(M.synced_at)).where(M.ad_account_id.in_(ids)))


def differing_attribution(
    db: Session, *, accounts: Collection[AdAccount], since: date, until: date
) -> bool:
    """Whether any account is set to another window than the one asked."""
    ids = [account.id for account in accounts]
    if not ids:
        return False
    return (
        db.scalar(
            select(M.id)
            .where(
                M.ad_account_id.in_(ids),
                M.date >= since,
                M.date <= until,
                M.attribution_setting != "",
            )
            .limit(1)
        )
        is not None
    )


__all__ = ["READS", "differing_attribution", "figures_by", "last_read_on"]
