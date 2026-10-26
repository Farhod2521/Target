"""Reads for Google: one preparation and what its screens draw, and the Ads screen."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID

from googleadskit import BUDGET_CONSTRAINED
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads.constants import ACTION_STALE_MINUTES
from app.modules.ads.models import AdSet, Campaign, GoogleLaunch
from app.modules.audit.constants import ActionStatus
from app.modules.audit.models import ActionLog
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount

PERIODS: Final[dict[str, int]] = {"today": 1, "7": 7, "30": 30}
DEFAULT_PERIOD: Final = "7"


def google_launch_for(
    db: Session, *, owner: User, launch_id: UUID | str
) -> GoogleLaunch | None:
    """This owner's preparation, or ``None`` - never somebody else's."""
    try:
        pk = UUID(str(launch_id))
    except ValueError:
        return None
    return db.scalar(
        select(GoogleLaunch).where(
            GoogleLaunch.owner_id == owner.id, GoogleLaunch.id == pk
        )
    )


def launch_profile(db: Session, *, launch: GoogleLaunch) -> Business | None:
    from app.modules.businesses.selectors import google_profile

    return google_profile(db, owner=launch.owner, account=launch.ad_account)


@dataclass(frozen=True, slots=True)
class SearchPreview:
    display_url: str
    headline: str
    description: str


def search_preview(*, launch: GoogleLaunch) -> SearchPreview:
    """Three headlines and two descriptions, as Google most often joins them."""
    host = urlsplit(launch.final_url).hostname or launch.final_url
    host = host.removeprefix("www.")
    path = "/".join(part for part in (launch.path1, launch.path2) if part)
    return SearchPreview(
        display_url=f"{host}/{path}" if path else host,
        headline=" | ".join(list(launch.headlines or [])[:3]),
        description=" ".join(list(launch.descriptions or [])[:2]),
    )


def keyword_rows(*, launch: GoogleLaunch) -> list[dict[str, Any]]:
    volumes = launch.volumes or {}
    return [
        {"text": row["text"], "searches": volumes.get(row["text"])}
        for row in launch.keywords or []
    ]


# -- the Google Ads screen -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Figures:
    spend_minor: int = 0
    impressions: int = 0
    clicks: int = 0
    results: int = 0

    @property
    def cost_per_result_minor(self) -> int | None:
        if not self.results:
            return None
        return round(self.spend_minor / self.results)


@dataclass(frozen=True, slots=True)
class GroupRow:
    group: AdSet
    figures: Figures
    pending: bool


@dataclass(frozen=True, slots=True)
class CampaignRow:
    campaign: Campaign
    figures: Figures
    pending: bool
    groups: tuple[GroupRow, ...] = ()
    shares_with: tuple[str, ...] = ()

    @property
    def budget_held(self) -> bool:
        return any(
            isinstance(item, dict) and item.get("code") == BUDGET_CONSTRAINED
            for item in self.campaign.recommendations or ()
        )

    @property
    def budget_typed(self) -> Decimal | None:
        minor = self.campaign.daily_budget_minor
        if minor is None:
            return None
        rules = provider_money(provider=self.campaign.provider)
        amount = Decimal(minor).scaleb(-rules.decimal_places(self.campaign.currency))
        whole = amount.to_integral_value()
        return whole if amount == whole else amount


@dataclass(frozen=True, slots=True)
class GoogleScreen:
    account: AdAccount
    accounts: tuple[AdAccount, ...]
    period: str
    since: date
    until: date
    totals: Figures
    campaigns: tuple[CampaignRow, ...] = field(default_factory=tuple)

    @property
    def any_pending(self) -> bool:
        return any(
            row.pending or any(group.pending for group in row.groups)
            for row in self.campaigns
        )


def google_screen(
    db: Session, *, owner: User, period: str = DEFAULT_PERIOD
) -> GoogleScreen | None:
    """The screen for the current Google account, or ``None`` with none added."""
    from app.modules.integrations.selectors.google import (
        current_google_account,
        subscribed_google_accounts,
    )

    account = current_google_account(db, owner=owner)
    if account is None:
        return None
    period = period if period in PERIODS else DEFAULT_PERIOD
    until = utcnow().astimezone(account.tzinfo()).date()
    since = until - timedelta(days=PERIODS[period] - 1)
    return GoogleScreen(
        account=account,
        accounts=tuple(subscribed_google_accounts(db, owner=owner)),
        period=period,
        since=since,
        until=until,
        totals=_sum(_figures(db, owner, account, since, until, "campaign").values()),
        campaigns=_rows(db, owner, account, since, until),
    )


def _rows(
    db: Session, owner: User, account: AdAccount, since: date, until: date
) -> tuple[CampaignRow, ...]:
    campaigns = list(
        db.scalars(
            select(Campaign)
            .where(Campaign.owner_id == owner.id, Campaign.ad_account_id == account.id)
            .order_by(Campaign.name)
        )
    )
    groups = list(
        db.scalars(
            select(AdSet)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(AdSet.owner_id == owner.id, Campaign.ad_account_id == account.id)
            .order_by(AdSet.name)
        )
    )
    by_campaign = _figures(db, owner, account, since, until, "campaign")
    by_group = _figures(db, owner, account, since, until, "adset")
    pending = _pending(
        db,
        owner,
        [row.external_id for row in campaigns] + [row.external_id for row in groups],
    )
    groups_of: dict[UUID, list[GroupRow]] = defaultdict(list)
    for group in groups:
        groups_of[group.campaign_id].append(
            GroupRow(
                group=group,
                figures=by_group.get(group.external_id, Figures()),
                pending=group.external_id in pending,
            )
        )
    sharing = _by_shared_budget(campaigns)
    return tuple(
        CampaignRow(
            campaign=campaign,
            figures=by_campaign.get(campaign.external_id, Figures()),
            pending=campaign.external_id in pending,
            groups=tuple(groups_of.get(campaign.id, ())),
            shares_with=tuple(
                other.name or other.external_id
                for other in sharing.get(campaign.shared_budget_id, ())
                if other.id != campaign.id
            ),
        )
        for campaign in campaigns
    )


def _by_shared_budget(campaigns: list[Campaign]) -> dict[str, list[Campaign]]:
    sharing: dict[str, list[Campaign]] = defaultdict(list)
    for campaign in campaigns:
        if campaign.shared_budget_id:
            sharing[campaign.shared_budget_id].append(campaign)
    return sharing


def _figures(
    db: Session, owner: User, account: AdAccount, since: date, until: date, level: str
) -> dict[str, Figures]:
    from app.modules.metrics.models import MetricsDaily

    key = (
        MetricsDaily.campaign_external_id
        if level == "campaign"
        else MetricsDaily.adset_external_id
    )
    rows = db.execute(
        select(
            key,
            func.sum(MetricsDaily.spend_minor),
            func.sum(MetricsDaily.impressions),
            func.sum(MetricsDaily.clicks),
            func.sum(MetricsDaily.results_reported),
        )
        .where(
            MetricsDaily.owner_id == owner.id,
            MetricsDaily.ad_account_id == account.id,
            MetricsDaily.level == level,
            MetricsDaily.date.between(since, until),
        )
        .group_by(key)
    )
    return {
        external_id: Figures(
            spend_minor=int(spend or 0),
            impressions=int(impressions or 0),
            clicks=int(clicks or 0),
            results=int(results or 0),
        )
        for external_id, spend, impressions, clicks, results in rows
    }


def _sum(figures: Iterable[Figures]) -> Figures:
    rows = list(figures)
    return Figures(
        spend_minor=sum(row.spend_minor for row in rows),
        impressions=sum(row.impressions for row in rows),
        clicks=sum(row.clicks for row in rows),
        results=sum(row.results for row in rows),
    )


def _pending(db: Session, owner: User, external_ids: list[str]) -> frozenset[str]:
    if not external_ids:
        return frozenset()
    cutoff = utcnow() - timedelta(minutes=ACTION_STALE_MINUTES)
    return frozenset(
        db.scalars(
            select(ActionLog.target_external_id).where(
                ActionLog.owner_id == owner.id,
                ActionLog.status == str(ActionStatus.PENDING),
                ActionLog.created_at >= cutoff,
                ActionLog.target_external_id.in_(external_ids),
            )
        )
    )
