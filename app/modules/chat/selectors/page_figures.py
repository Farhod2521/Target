"""The window's figures, read across the subscription and split by page, and the days before it."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.briefs import delivery_label
from app.modules.chat.selectors.result_counts import (
    KindSums,
    count_of,
    digests,
    figure_sums,
    kind_of,
    merged,
)
from app.modules.chat.selectors.scope import in_subscription, lead_window
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from core.chat.context import PriorDigest
from core.chat.prior import KindTotal, moves


@dataclass(frozen=True, slots=True)
class CampaignSums:
    """One campaign over the window, summed from the groups left to it."""

    external_id: str
    name: str
    status: str
    spend_minor: int
    results: tuple[KindSums, ...] = ()


@dataclass(frozen=True, slots=True)
class PageSums:
    """One page over the window: what it spent, brought in, and through what."""

    external_id: str
    name: str
    spend_minor: int
    results: tuple[KindSums, ...]
    campaigns: tuple[CampaignSums, ...]


def page_sums(
    db: Session,
    *,
    owner: User,
    scope: PageScope,
    since: date,
    until: date,
    without: frozenset[str] = frozenset(),
) -> tuple[PageSums, ...]:
    """Every page in the subscription over the window, biggest spender first."""
    kept = tuple(
        adset_id
        for adset_id in scope.adset_ids
        if scope.campaign_of.get(adset_id, "") not in without
    )
    found = _figures(db, owner=owner, adset_ids=kept, since=since, until=until)
    leads = _leads(db, owner=owner, adset_ids=kept, since=since, until=until)
    goals = _goals(db, owner=owner, adset_ids=kept)
    mirror = _mirror(db, owner=owner, campaign_ids=scope.campaign_ids)

    held = set(kept)
    grouped = {
        page_id: [adset_id for adset_id in adset_ids if adset_id in held]
        for page_id, adset_ids in scope.adsets_by_page().items()
    }
    for page_id in scope.pages:
        grouped.setdefault(page_id, [])
    pages = [
        _page(
            page_id=page_id,
            name=scope.name_of(page_id),
            adset_ids=adset_ids,
            figures=found,
            leads=leads,
            goals=goals,
            campaign_of=scope.campaign_of,
            mirror=mirror,
        )
        for page_id, adset_ids in grouped.items()
    ]
    return tuple(sorted(pages, key=lambda row: -row.spend_minor))


def _page(
    *,
    page_id: str,
    name: str,
    adset_ids: list[str],
    figures: dict[str, Mapping[str, Any]],
    leads: dict[str, int],
    goals: dict[str, tuple[str, Mapping[str, Any] | None]],
    campaign_of: dict[str, str],
    mirror: dict[str, dict[str, str]],
) -> PageSums:
    spent: dict[str, int] = {}
    counted: dict[str, list[KindSums]] = {}
    for adset_id in adset_ids:
        campaign = campaign_of.get(adset_id, "")
        if not campaign:
            continue
        own = figures.get(adset_id, {})
        spend = int(own.get("spend") or 0)
        spent[campaign] = spent.get(campaign, 0) + spend
        kind = kind_of(*goals.get(adset_id, ("", None)))
        count = count_of(kind, figures=own, leads=leads.get(adset_id, 0))
        if count is not None:
            counted.setdefault(campaign, []).append(
                KindSums(kind=kind, count=count, spend_minor=spend)
            )
    campaigns = sorted(
        (
            CampaignSums(
                external_id=campaign,
                name=mirror.get(campaign, {}).get("name") or campaign,
                status=mirror.get(campaign, {}).get("status", ""),
                spend_minor=spend,
                results=merged(counted.get(campaign, ())),
            )
            for campaign, spend in spent.items()
        ),
        key=lambda row: -row.spend_minor,
    )
    return PageSums(
        external_id=page_id,
        name=name,
        spend_minor=sum(row.spend_minor for row in campaigns),
        results=merged(item for row in campaigns for item in row.results),
        campaigns=tuple(campaigns),
    )


def _figures(
    db: Session, *, owner: User, adset_ids: tuple[str, ...], since: date, until: date
) -> dict[str, Mapping[str, Any]]:
    if not adset_ids:
        return {}
    rows = db.execute(
        select(MetricsDaily.adset_external_id, *figure_sums())
        .where(
            MetricsDaily.owner_id == owner.id,
            in_subscription(MetricsDaily.ad_account_id),
            MetricsDaily.level == MetricLevel.ADSET,
            MetricsDaily.adset_external_id.in_(list(adset_ids)),
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
        )
        .group_by(MetricsDaily.adset_external_id)
    ).mappings()
    return {row["adset_external_id"]: row for row in rows}


def _goals(
    db: Session, *, owner: User, adset_ids: tuple[str, ...]
) -> dict[str, tuple[str, Mapping[str, Any] | None]]:
    if not adset_ids:
        return {}
    return {
        external_id: (goal or "", promoted if isinstance(promoted, Mapping) else None)
        for external_id, goal, promoted in db.execute(
            select(
                AdSet.external_id,
                AdSet.optimization_goal_raw,
                AdSet.promoted_object_raw,
            ).where(AdSet.owner_id == owner.id, AdSet.external_id.in_(list(adset_ids)))
        )
    }


def _leads(
    db: Session, *, owner: User, adset_ids: tuple[str, ...], since: date, until: date
) -> dict[str, int]:
    from app.modules.leads.selectors import counts_by_adset

    if not adset_ids:
        return {}
    start, end = lead_window(db, owner=owner, since=since, until=until)
    wanted = set(adset_ids)
    counted = counts_by_adset(db, owner=owner, since=start, until=end)
    return {key: pair[0] for key, pair in counted.items() if key in wanted}


def _mirror(
    db: Session, *, owner: User, campaign_ids: tuple[str, ...]
) -> dict[str, dict[str, str]]:
    if not campaign_ids:
        return {}
    rows = db.scalars(
        select(Campaign).where(
            Campaign.owner_id == owner.id, Campaign.external_id.in_(list(campaign_ids))
        )
    )
    return {
        row.external_id: {
            "name": row.name or row.external_id,
            "status": str(delivery_label(row.delivery)),
        }
        for row in rows
    }


def prior_digest(
    db: Session,
    *,
    owner: User,
    scope: PageScope,
    since: date,
    days: int,
    without: frozenset[str],
    window: tuple[PageSums, ...],
    currency: str,
) -> PriorDigest | None:
    """The ``days`` before ``since``, against ``window``. ``None`` if nothing spent."""
    before = page_sums(
        db,
        owner=owner,
        scope=scope,
        since=since - timedelta(days=days),
        until=since - timedelta(days=1),
        without=without,
    )
    spent = sum(row.spend_minor for row in before)
    if spent <= 0:
        return None
    then = merged(item for row in before for item in row.results)
    now = merged(item for row in window for item in row.results)
    return PriorDigest(
        spend=format_minor(amount_minor=spent, currency=currency) or "0",
        results=digests(then, currency=currency),
        moves=moves(
            spend_now=sum(row.spend_minor for row in window),
            spend_before=spent,
            now=_totals(now),
            before=_totals(then),
        ),
    )


def _totals(items: Iterable[KindSums]) -> list[KindTotal]:
    return [
        KindTotal(kind=item.kind, count=item.count, spend_minor=item.spend_minor)
        for item in items
    ]


__all__ = ["CampaignSums", "PageSums", "page_sums", "prior_digest"]
