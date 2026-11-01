"""Everything one day's reports are built from, read once for every pair.

**Read whole, sliced afterwards.** Every figure is read across the whole
subscription in one pass and split by pair in
:mod:`app.modules.chat.selectors.daily`: a pass per pair would multiply every
query by the number of pairs.

**The ad group is the unit.** A page is found through the group, so the group
is what is placed, and the campaign is read around it. Campaigns built in Ads
Manager are reported beside the ones built here: a pair's total is everything
the pair spent, and ``built`` says which is which.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Final

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign
from app.modules.chat.selectors.day_lines import report_money
from app.modules.chat.selectors.scope import in_subscription, subscribed_pages
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily

# How far back an Ads Manager campaign that is switched on but silent still
# counts as working. Most of them have not spent for months: one pair held 258.
IDLE_LOOKBACK_DAYS: Final = 7

COLUMNS: Final[dict[str, str]] = {
    "spend": "spend_minor",
    "impressions": "impressions",
    "link_clicks": "inline_link_clicks",
    "results": "results_reported",
    "recallers": "recallers",
    "profile_visits": "profile_visits",
    "reported": "leads_reported",
}


@dataclass(frozen=True, slots=True)
class Mirror:
    """What the campaign mirror says about one campaign."""

    pk: str
    name: str
    goal: str
    delivery: str
    learning: bool
    promoted: Mapping[str, Any] | None = None
    created_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class Group:
    """What the mirror says about one ad group: its goal and its state now."""

    name: str
    delivery: str
    goal: str = ""
    promoted: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DayTables:
    """One owner's day, before it is split by pair. Keyed by ad group, except
    ``mirror`` by campaign and ``pages`` by page."""

    sums: dict[str, dict[str, int]] = field(default_factory=dict)
    ours: dict[str, int] = field(default_factory=dict)
    # The same two over the period before.
    before: dict[str, dict[str, int]] = field(default_factory=dict)
    ours_before: dict[str, int] = field(default_factory=dict)
    campaign_of: dict[str, str] = field(default_factory=dict)
    # The campaigns this product built; the rest are Ads Manager's.
    built: frozenset[str] = frozenset()
    # The campaigns that spent in the days before this one.
    lately: frozenset[str] = frozenset()
    mirror: dict[str, Mirror] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)
    # The groups that did something that day, or may be silent since.
    groups: dict[str, Group] = field(default_factory=dict)


def day_tables(
    db: Session,
    *,
    owner: User,
    since: date,
    until: date,
    lead_window: tuple[datetime, datetime],
    before_window: tuple[datetime, datetime],
) -> DayTables:
    """The period's figures, per ad group, and the same length before it. The
    windows are its leads' on the cabinet's clock: a lead is stamped with an
    instant and a figure with a provider's day."""
    from app.modules.ads.selectors import all_launched_campaign_ids

    groups = _groups(db, owner=owner)
    sums = _sums(db, owner=owner, since=since, until=until)
    span = (until - since).days + 1
    lately = _lately(db, owner=owner, since=since)
    return DayTables(
        groups=_group_mirror(
            db,
            owner=owner,
            ids={*sums, *(g for g, c in groups.items() if c in lately)},
        ),
        sums=sums,
        before=_sums(
            db,
            owner=owner,
            since=since - timedelta(days=span),
            until=since - timedelta(days=1),
        ),
        ours=_ours(db, owner=owner, since=lead_window[0], until=lead_window[1]),
        ours_before=_ours(
            db, owner=owner, since=before_window[0], until=before_window[1]
        ),
        campaign_of=groups,
        built=all_launched_campaign_ids(db, owner=owner),
        lately=lately,
        mirror=_mirror(db, owner=owner),
        pages=_pages(db, owner=owner),
    )


def _group_mirror(db: Session, *, owner: User, ids: Iterable[str]) -> dict[str, Group]:
    """``{ad group id: name, goal and state}``."""
    wanted = list(ids)
    if not wanted:
        return {}
    rows = db.execute(
        select(
            AdSet.external_id,
            AdSet.name,
            AdSet.delivery,
            AdSet.optimization_goal_raw,
            AdSet.promoted_object_raw,
        ).where(AdSet.owner_id == owner.id, AdSet.external_id.in_(wanted))
    )
    return {
        external_id: Group(
            name=name or external_id,
            delivery=delivery or "",
            goal=goal or "",
            promoted=promoted if isinstance(promoted, Mapping) else None,
        )
        for external_id, name, delivery, goal, promoted in rows
    }


def _groups(db: Session, *, owner: User) -> dict[str, str]:
    """``{ad group id: campaign id}`` for every group in the subscription."""
    return dict(
        db.execute(
            select(AdSet.external_id, Campaign.external_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                in_subscription(Campaign.ad_account_id),
                Campaign.external_id != "",
            )
        ).all()
    )


def _sums(
    db: Session, *, owner: User, since: date, until: date
) -> dict[str, dict[str, int]]:
    """What each ad group did between two days, inclusive."""
    rows = db.execute(
        select(
            MetricsDaily.adset_external_id,
            *(
                func.sum(getattr(MetricsDaily, column)).label(name)
                for name, column in COLUMNS.items()
            ),
        )
        .where(
            MetricsDaily.owner_id == owner.id,
            in_subscription(MetricsDaily.ad_account_id),
            MetricsDaily.level == MetricLevel.ADSET,
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            MetricsDaily.adset_external_id != "",
        )
        .group_by(MetricsDaily.adset_external_id)
    ).mappings()
    return {
        row["adset_external_id"]: {name: int(row[name] or 0) for name in COLUMNS}
        for row in rows
    }


def _lately(db: Session, *, owner: User, since: date) -> frozenset[str]:
    """The campaigns with money in the days just before ``since``."""
    rows = db.scalars(
        select(MetricsDaily.campaign_external_id)
        .where(
            MetricsDaily.owner_id == owner.id,
            in_subscription(MetricsDaily.ad_account_id),
            MetricsDaily.level == MetricLevel.ADSET,
            MetricsDaily.date >= since - timedelta(days=IDLE_LOOKBACK_DAYS),
            MetricsDaily.date < since,
            MetricsDaily.spend_minor > 0,
            MetricsDaily.campaign_external_id != "",
        )
        .distinct()
    )
    return frozenset(rows)


def outside_spend(
    db: Session, *, owner: User, since: date, until: date, placed: Iterable[str]
) -> tuple[str, ...]:
    """What the groups in no chosen pair spent, one text a currency."""
    inside = set(placed)
    money = func.sum(MetricsDaily.spend_minor)
    rows = db.execute(
        select(MetricsDaily.adset_external_id, MetricsDaily.currency, money)
        .where(
            MetricsDaily.owner_id == owner.id,
            in_subscription(MetricsDaily.ad_account_id),
            MetricsDaily.level == MetricLevel.ADSET,
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            MetricsDaily.adset_external_id != "",
        )
        .group_by(MetricsDaily.adset_external_id, MetricsDaily.currency)
        .having(money > 0)
    )
    spent: dict[str, int] = {}
    for group, currency, amount in rows:
        if group not in inside:
            spent[currency] = spent.get(currency, 0) + int(amount)
    return tuple(
        report_money(amount, currency)
        for currency, amount in sorted(spent.items(), key=lambda row: -row[1])
    )


def _ours(
    db: Session, *, owner: User, since: datetime, until: datetime
) -> dict[str, int]:
    """The enquiries this product received, per ad group."""
    from app.modules.leads.selectors import counts_by_adset

    return {
        key: counts[0]
        for key, counts in counts_by_adset(
            db, owner=owner, since=since, until=until
        ).items()
    }


def _mirror(db: Session, *, owner: User) -> dict[str, Mirror]:
    """``{campaign id: what the mirror says}`` - name, goal, state, learning."""
    from app.modules.metrics.selectors.campaigns import goal_order

    group = aliased(AdSet)
    speaker = (
        select(AdSet.id)
        .where(AdSet.owner_id == owner.id, AdSet.campaign_id == Campaign.id)
        .order_by(*goal_order())
        .limit(1)
        .scalar_subquery()
    )
    first = aliased(AdSet)
    learning = exists().where(
        group.owner_id == owner.id,
        group.campaign_id == Campaign.id,
        group.is_learning.is_(True),
    )
    rows = db.execute(
        select(
            Campaign.id,
            Campaign.external_id,
            Campaign.name,
            Campaign.delivery,
            Campaign.created_time,
            first.optimization_goal_raw,
            first.promoted_object_raw,
            learning.label("learning"),
        )
        .outerjoin(first, first.id == speaker)
        .where(Campaign.owner_id == owner.id, in_subscription(Campaign.ad_account_id))
    )
    return {
        external_id: Mirror(
            pk=str(pk),
            name=name or external_id,
            goal=goal or "",
            promoted=promoted if isinstance(promoted, Mapping) else None,
            delivery=delivery or "",
            learning=bool(is_learning),
            created_time=created_time,
        )
        for pk, external_id, name, delivery, created_time, goal, promoted, is_learning in rows
    }


def _pages(db: Session, *, owner: User) -> dict[str, str]:
    """``{page id: its name}`` for the pages the subscription carries."""
    return {
        page.external_id: page.name or page.external_id
        for page in subscribed_pages(db, owner=owner)
    }


__all__ = [
    "COLUMNS",
    "IDLE_LOOKBACK_DAYS",
    "DayTables",
    "Group",
    "Mirror",
    "day_tables",
    "outside_spend",
]
