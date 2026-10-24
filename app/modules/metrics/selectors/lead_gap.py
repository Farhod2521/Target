"""Leads Meta counted against leads that reached us, and the pages that went quiet."""

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount, PageAccount, ProviderConnection
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where, end_of, start_of
from core.metrics import (
    ALARM_GAP_MISSING,
    ALARM_GAP_PCT,
    LEAD_GOALS,
    SCREEN_GAP_MISSING,
    SCREEN_GAP_PCT,
    PanelTotals,
    missing_leads,
)

GAP_DAYS = 7
WEBSITE = "WEBSITE"
UTC = ZoneInfo("UTC")
GAP_NOTE = (
    "Meta %(reported)s ta murojaat sanagan, bu yerga %(ours)s tasi yetib kelgan - "
    "narx noto'g'ri chiqmasligi uchun ko'rsatilmadi."
)


@dataclass(frozen=True, slots=True)
class LeadGap:
    reported: int
    ours: int
    missing: int
    pages: tuple[str, ...]
    since: date
    until: date


@dataclass(frozen=True, slots=True)
class OwnerLeads:
    owner_id: uuid.UUID
    email: str
    reported: int
    ours: int

    @property
    def missing(self) -> int:
        return max(0, self.reported - self.ours)


@dataclass(frozen=True, slots=True)
class UnheardPage:
    page_id: str
    name: str
    reported: int


def form_groups(owner: User | None = None) -> Select[Any]:
    """Ad sets whose result is a lead form, not a website visit."""
    from app.modules.ads.models import AdSet

    query = select(AdSet).where(
        AdSet.optimization_goal_raw.in_(list(LEAD_GOALS)),
        AdSet.destination_type_raw != WEBSITE,
    )
    if owner is not None:
        query = query.where(AdSet.owner_id == owner.id)
    return query


def _groups_on(
    db: Session, *, owner: User, accounts: Collection[Any], hidden: Collection[str] = ()
) -> dict[str, Any]:
    from app.modules.ads.models import AdSet, Campaign

    query = (
        form_groups(owner)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(Campaign.ad_account_id.in_([a.id for a in accounts]))
        .with_only_columns(AdSet.external_id, AdSet.promoted_object_raw)
    )
    if hidden:
        query = query.where(AdSet.external_id.not_in(list(hidden)))
    return dict(db.execute(query).all())


def _counts(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    groups: list[str],
    since: date,
    until: date,
) -> tuple[dict[str, int], dict[str, int]]:
    from app.modules.leads.selectors import counts_by_adset

    tzinfo = account.tzinfo()
    reported = dict(
        db.execute(
            select(
                MetricsDaily.adset_external_id, func.sum(MetricsDaily.leads_reported)
            )
            .where(
                *cabinet_where(db, owner=owner, account=account),
                MetricsDaily.date >= since,
                MetricsDaily.date <= until,
                MetricsDaily.adset_external_id.in_(groups),
            )
            .group_by(MetricsDaily.adset_external_id)
        ).all()
    )
    counted = counts_by_adset(
        db, owner=owner, since=start_of(since, tzinfo), until=end_of(until, tzinfo)
    )
    return (
        {key: int(reported.get(key) or 0) for key in groups},
        {key: counted.get(key, (0, 0))[0] for key in groups},
    )


def lead_gap(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    now: datetime,
    hidden_adsets: Collection[str] = (),
) -> LeadGap | None:
    until = now.astimezone(account.tzinfo()).date() - timedelta(days=1)
    since = until - timedelta(days=GAP_DAYS - 1)
    groups = _groups_on(db, owner=owner, accounts=[account], hidden=hidden_adsets)
    if not groups:
        return None
    reported, ours = _counts(
        db, owner=owner, account=account, groups=list(groups), since=since, until=until
    )
    total_reported, total_ours = sum(reported.values()), sum(ours.values())
    missing = missing_leads(
        reported=total_reported,
        ours=total_ours,
        share_pct=ALARM_GAP_PCT,
        at_least=ALARM_GAP_MISSING,
    )
    if not missing:
        return None
    short = [key for key in groups if reported[key] > ours[key]]
    return LeadGap(
        reported=total_reported,
        ours=total_ours,
        missing=missing,
        pages=_page_names(db, owner=owner, promoted=(groups[key] for key in short)),
        since=since,
        until=until,
    )


def unheard_pages(
    db: Session, *, owner: User, accounts: Collection[AdAccount], now: datetime
) -> list[UnheardPage]:
    groups = _groups_on(db, owner=owner, accounts=accounts)
    page_of = {
        key: str(value["page_id"])
        for key, value in groups.items()
        if isinstance(value, dict) and value.get("page_id")
    }
    if not page_of:
        return []
    until = now.astimezone(UTC).date()
    rows = db.execute(
        select(MetricsDaily.external_id, func.sum(MetricsDaily.leads_reported))
        .where(
            MetricsDaily.owner_id == owner.id,
            MetricsDaily.level == str(MetricLevel.ADSET),
            MetricsDaily.external_id.in_(list(page_of)),
            MetricsDaily.date >= until - timedelta(days=GAP_DAYS - 1),
            MetricsDaily.date <= until,
        )
        .group_by(MetricsDaily.external_id)
    )
    reported: dict[str, int] = {}
    for adset_id, total in rows:
        page = page_of[adset_id]
        reported[page] = reported.get(page, 0) + int(total or 0)
    loud = [page for page, count in reported.items() if count]
    if not loud:
        return []
    pages = db.scalars(
        select(PageAccount)
        .join(ProviderConnection, ProviderConnection.id == PageAccount.connection_id)
        .where(
            PageAccount.owner_id == owner.id,
            PageAccount.external_id.in_(loud),
            PageAccount.leadgen_subscribed.is_(False),
            ProviderConnection.status.in_([str(s) for s in USABLE_CONNECTION_STATUSES]),
        )
    )
    found = [
        UnheardPage(
            page_id=str(page.id),
            name=page.name or page.external_id,
            reported=reported[page.external_id],
        )
        for page in pages
    ]
    return sorted(found, key=lambda one: -one.reported)


def short_pages_today(
    db: Session, *, owner: User, account: AdAccount, now: datetime
) -> set[str]:
    today = now.astimezone(account.tzinfo()).date()
    groups = _groups_on(db, owner=owner, accounts=[account])
    if not groups:
        return set()
    reported, ours = _counts(
        db, owner=owner, account=account, groups=list(groups), since=today, until=today
    )
    return {
        str(groups[key]["page_id"])
        for key in groups
        if reported[key] > ours[key]
        and isinstance(groups[key], dict)
        and groups[key].get("page_id")
    }


def lead_counts_everywhere(
    db: Session, *, now: datetime, days: int = GAP_DAYS
) -> list[OwnerLeads]:
    from app.modules.ads.models import AdSet
    from app.modules.leads.selectors import lead_counts_by_owner

    until = now.date() - timedelta(days=1)
    since = until - timedelta(days=days - 1)
    ids = form_groups().with_only_columns(AdSet.external_id)
    rows = db.execute(
        select(MetricsDaily.owner_id, User.email, func.sum(MetricsDaily.leads_reported))
        .join(User, User.id == MetricsDaily.owner_id)
        .where(
            MetricsDaily.level == str(MetricLevel.ADSET),
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            MetricsDaily.adset_external_id.in_(ids),
        )
        .group_by(MetricsDaily.owner_id, User.email)
    )
    ours = lead_counts_by_owner(
        db, since=start_of(since, UTC), until=end_of(until, UTC), adset_ids=ids
    )
    found = [
        OwnerLeads(
            owner_id=owner_id,
            email=email,
            reported=int(total or 0),
            ours=ours.get(owner_id, 0),
        )
        for owner_id, email, total in rows
    ]
    return sorted(found, key=lambda row: -row.missing)


def lead_gaps_everywhere(
    db: Session, *, now: datetime, limit: int | None = 20
) -> list[OwnerLeads]:
    return [
        row
        for row in lead_counts_everywhere(db, now=now)
        if missing_leads(
            reported=row.reported,
            ours=row.ours,
            share_pct=ALARM_GAP_PCT,
            at_least=ALARM_GAP_MISSING,
        )
    ][:limit]


def withheld_cost_note(totals: PanelTotals) -> str:
    missing = missing_leads(
        reported=totals.leads_reported,
        ours=totals.leads,
        share_pct=SCREEN_GAP_PCT,
        at_least=SCREEN_GAP_MISSING,
    )
    if not missing:
        return ""
    return GAP_NOTE % {"reported": totals.leads_reported, "ours": totals.leads}


def _page_names(
    db: Session, *, owner: User, promoted: Iterable[object]
) -> tuple[str, ...]:
    ids = {
        str(value.get("page_id"))
        for value in promoted
        if isinstance(value, dict) and value.get("page_id")
    }
    if not ids:
        return ()
    names = db.scalars(
        select(PageAccount.name)
        .where(PageAccount.owner_id == owner.id, PageAccount.external_id.in_(ids))
        .order_by(PageAccount.name)
    )
    return tuple(name for name in names if name)
