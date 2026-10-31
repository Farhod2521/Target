"""Everything one day's reports are built from, read once for every pair.

**Read whole, sliced afterwards.** Every figure is read across the whole
subscription in one pass and split by pair in
:mod:`app.modules.chat.selectors.daily`: a pass per pair would multiply every
query by the number of pairs.

**The ad group is the unit.** A page is found through the group, so the group
is what is placed, and the campaign and the advert are read around it. Only
campaigns this product built are reported, the rule the figures screen keeps.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.chat.selectors.scope import in_subscription, subscribed_pages
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily

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
    """What the mirror says about one ad group: its name and its state now."""

    name: str
    delivery: str


@dataclass(frozen=True, slots=True)
class AdRow:
    """One advert that spent that day: its group, its name, its figures."""

    adset_id: str
    name: str
    sums: dict[str, int]
    ours: int = 0


@dataclass(frozen=True, slots=True)
class DayTables:
    """One owner's day, before it is split by pair. Keyed by ad group, except
    ``mirror`` by campaign, ``pages`` by page and ``ads`` by advert."""

    sums: dict[str, dict[str, int]] = field(default_factory=dict)
    ours: dict[str, int] = field(default_factory=dict)
    # Groups of the campaigns built here, which are the report.
    campaign_of: dict[str, str] = field(default_factory=dict)
    mirror: dict[str, Mirror] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
    # Only the adverts that spent that day.
    ads: dict[str, AdRow] = field(default_factory=dict)


def day_tables(
    db: Session, *, owner: User, day: date, start: datetime, end: datetime
) -> DayTables:
    """The day's figures, per ad group. ``start`` and ``end`` are the day's
    lead window on the cabinet's clock: a lead is stamped with an instant and
    a figure with a provider's day."""
    from app.modules.ads.selectors import all_launched_campaign_ids

    groups = _groups(db, owner=owner)
    built_here = all_launched_campaign_ids(db, owner=owner)
    sums = _sums(db, owner=owner, since=day, until=day)
    return DayTables(
        groups=_group_mirror(db, owner=owner, ids=sums),
        ads=_ads(db, owner=owner, day=day, start=start, end=end),
        sums=sums,
        ours=_ours(db, owner=owner, since=start, until=end),
        campaign_of={
            group: campaign
            for group, campaign in groups.items()
            if campaign in built_here
        },
        mirror=_mirror(db, owner=owner),
        pages=_pages(db, owner=owner),
    )


def _group_mirror(db: Session, *, owner: User, ids: Iterable[str]) -> dict[str, Group]:
    """``{ad group id: name and state}`` for the groups that spent."""
    wanted = list(ids)
    if not wanted:
        return {}
    rows = db.execute(
        select(AdSet.external_id, AdSet.name, AdSet.delivery).where(
            AdSet.owner_id == owner.id, AdSet.external_id.in_(wanted)
        )
    )
    return {
        external_id: Group(name=name or external_id, delivery=delivery or "")
        for external_id, name, delivery in rows
    }


def _ads(
    db: Session, *, owner: User, day: date, start: datetime, end: datetime
) -> dict[str, AdRow]:
    """``{ad id: its day}`` for every advert that spent - the advert's own
    rows. One the mirror has not stored yet is still listed, under its id."""
    from app.modules.leads.selectors import counts_by_ad

    rows = db.execute(
        select(
            MetricsDaily.ad_external_id,
            MetricsDaily.adset_external_id,
            *(
                func.sum(getattr(MetricsDaily, column)).label(name)
                for name, column in COLUMNS.items()
            ),
        )
        .where(
            MetricsDaily.owner_id == owner.id,
            in_subscription(MetricsDaily.ad_account_id),
            MetricsDaily.level == MetricLevel.AD,
            MetricsDaily.date == day,
            MetricsDaily.spend_minor > 0,
            MetricsDaily.ad_external_id != "",
        )
        .group_by(MetricsDaily.ad_external_id, MetricsDaily.adset_external_id)
    ).mappings()
    found = {row["ad_external_id"]: row for row in rows}
    if not found:
        return {}
    names = dict(
        db.execute(
            select(Ad.external_id, Ad.name).where(
                Ad.owner_id == owner.id, Ad.external_id.in_(list(found))
            )
        ).all()
    )
    ours = counts_by_ad(db, owner=owner, since=start, until=end)
    return {
        ad_id: AdRow(
            adset_id=row["adset_external_id"],
            name=names.get(ad_id) or ad_id,
            sums={name: int(row[name] or 0) for name in COLUMNS},
            ours=ours.get(ad_id, (0, 0))[0],
        )
        for ad_id, row in found.items()
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


__all__ = ["COLUMNS", "AdRow", "DayTables", "Group", "Mirror", "day_tables"]
