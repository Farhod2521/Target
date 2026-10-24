from dataclasses import dataclass
from datetime import datetime

from app.modules.ads.constants import NOT_RUNNING
from app.modules.ads.models import AdSet, Campaign
from core.targeting import AudienceSketch, describe


@dataclass(frozen=True, slots=True)
class RowSettings:
    daily_budget_minor: int | None
    currency: str
    audience: AudienceSketch | None
    groups: int
    ends_at: datetime | None = None
    spend_cap_minor: int | None = None
    starts_at: datetime | None = None
    spending_minor: int = 0

    @property
    def is_split(self) -> bool:
        return self.groups > 1


def row_settings(*, campaign: Campaign) -> RowSettings:
    groups = list(campaign.adsets)
    return RowSettings(
        daily_budget_minor=_daily(campaign=campaign, groups=groups),
        currency=_currency(campaign=campaign, groups=groups),
        audience=describe(groups[0].targeting_raw) if len(groups) == 1 else None,
        groups=len(groups),
        ends_at=groups[0].end_time if len(groups) == 1 else None,
        spend_cap_minor=campaign.spend_cap_minor,
        starts_at=min(
            (row.start_time for row in groups if row.start_time), default=None
        ),
        spending_minor=_spending(campaign=campaign, groups=groups),
    )


def group_settings(*, adset: AdSet, campaign: Campaign) -> RowSettings:
    return RowSettings(
        daily_budget_minor=adset.daily_budget_minor,
        currency=_currency(campaign=campaign, groups=[adset]),
        audience=describe(adset.targeting_raw),
        groups=1,
        ends_at=adset.end_time,
        starts_at=adset.start_time,
        spending_minor=adset.daily_budget_minor or 0 if _delivering(adset) else 0,
    )


def with_settings(*, campaigns: list[Campaign]) -> list[Campaign]:
    for campaign in campaigns:
        campaign.settings = row_settings(campaign=campaign)
    return campaigns


def daily_total(*, settings: list[RowSettings], currency: str) -> tuple[int, str]:
    total = sum(
        row.spending_minor
        for row in settings
        if not row.currency or row.currency == currency
    )
    return (total, currency)


def _daily(*, campaign: Campaign, groups: list[AdSet]) -> int | None:
    if campaign.daily_budget_minor is not None:
        return campaign.daily_budget_minor
    figures = [row.daily_budget_minor for row in groups if row.daily_budget_minor]
    return sum(figures) if figures else None


def _spending(*, campaign: Campaign, groups: list[AdSet]) -> int:
    delivering = [row for row in groups if _delivering(row)]
    if campaign.daily_budget_minor is not None:
        return campaign.daily_budget_minor if delivering or not groups else 0
    return sum(row.daily_budget_minor or 0 for row in delivering)


def _delivering(adset: AdSet) -> bool:
    return str(adset.delivery) not in NOT_RUNNING


def _currency(*, campaign: Campaign, groups: list[AdSet]) -> str:
    account = getattr(campaign, "ad_account", None)
    for value in (
        campaign.currency,
        next((row.currency for row in groups if row.currency), ""),
        getattr(account, "currency", ""),
    ):
        if value:
            return str(value)
    return ""


__all__ = ["RowSettings", "daily_total", "row_settings", "with_settings"]
