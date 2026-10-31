"""The Google Ads screen as the cabinet draws it: one account, its campaigns and groups."""

from typing import Any, Literal

from pydantic import Field

from app.common.contract import Camel, Money, money, zero_or
from app.modules.ads.contract.words import Status, status_word
from app.modules.ads.selectors.google import (
    CampaignRow,
    Figures,
    GoogleScreen,
    GroupRow,
)


class GoogleFigures(Camel):
    spend: Money
    impressions: int
    clicks: int
    results: int
    cost_per_result: Money | None


class GoogleGroup(Camel):
    id: str
    name: str
    delivery: Status
    pending: bool = Field(description="A press on it is still on its way to Google.")
    figures: GoogleFigures


class GoogleCampaign(Camel):
    id: str
    name: str
    delivery: Status
    pending: bool
    daily_budget: Money | None
    budget_held: bool = Field(description="Google shows it less for want of budget.")
    shares_with: list[str] = Field(
        description="Campaigns sharing this budget: a new amount applies to them too."
    )
    figures: GoogleFigures
    groups: list[GoogleGroup]


class GoogleAccount(Camel):
    id: str
    name: str
    currency: str


class ShownAccount(GoogleAccount):
    synced_at: str | None


class GoogleScreenOut(Camel):
    account: ShownAccount
    accounts: list[GoogleAccount]
    period: Literal["today", "7", "30"]
    totals: GoogleFigures
    campaigns: list[GoogleCampaign]
    any_pending: bool


class GoogleScreenAnswer(Camel):
    screen: GoogleScreenOut | None


def _figures(found: Figures, *, currency: str, provider: str) -> dict[str, Any]:
    return {
        "spend": zero_or(found.spend_minor, currency, provider=provider),
        "impressions": found.impressions,
        "clicks": found.clicks,
        "results": found.results,
        "cost_per_result": money(
            found.cost_per_result_minor, currency, provider=provider
        ),
    }


def _group(
    row: GroupRow, *, parent_paused: bool, currency: str, provider: str
) -> dict[str, Any]:
    own = status_word(row.group.delivery)
    return {
        "id": row.group.external_id,
        "name": row.group.name,
        "delivery": "paused_above" if parent_paused and own != "paused" else own,
        "pending": row.pending,
        "figures": _figures(row.figures, currency=currency, provider=provider),
    }


def _campaign(row: CampaignRow, *, currency: str, provider: str) -> dict[str, Any]:
    delivery = status_word(row.campaign.delivery)
    return {
        "id": row.campaign.external_id,
        "name": row.campaign.name,
        "delivery": delivery,
        "pending": row.pending,
        "daily_budget": money(
            row.campaign.daily_budget_minor, currency, provider=provider
        ),
        "budget_held": row.budget_held,
        "shares_with": list(row.shares_with),
        "figures": _figures(row.figures, currency=currency, provider=provider),
        "groups": [
            _group(
                group,
                parent_paused=delivery == "paused",
                currency=currency,
                provider=provider,
            )
            for group in row.groups
        ],
    }


def screen_of(found: GoogleScreen) -> GoogleScreenOut:
    account = found.account
    currency, provider = account.currency, account.provider
    return GoogleScreenOut.model_validate(
        {
            "account": {
                "id": account.external_id,
                "name": account.name,
                "currency": currency,
                "synced_at": account.synced_at.isoformat()
                if account.synced_at
                else None,
            },
            "accounts": [
                {"id": row.external_id, "name": row.name, "currency": row.currency}
                for row in found.accounts
            ],
            "period": found.period,
            "totals": _figures(found.totals, currency=currency, provider=provider),
            "campaigns": [
                _campaign(row, currency=currency, provider=provider)
                for row in found.campaigns
            ],
            "any_pending": found.any_pending,
        }
    )


__all__ = ["GoogleScreenAnswer", "screen_of"]
