"""The ChatGPT Ads section as the cabinet reads it: camelCase, money as integers."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from adskit.money import ISO_MONEY
from openaiadskit.accounts import PlaceInfo
from openaiadskit.metrics import Totals
from pydantic import Field

from app.common.contract import Camel, Money, money, zero_or
from app.modules.ads.contract.words import Status, status_word
from app.modules.chatgpt.constants import (
    API_KEY_MAX,
    CAMPAIGN_NAME_MAX,
    ISSUE_LABELS,
    REVIEW_LABELS,
)
from app.modules.chatgpt.services import CampaignDetail, Created, Screen
from app.modules.integrations.models import AdAccount

PROVIDER = "chatgpt"
Pressable = Literal["campaign", "adset", "ad"]

# -- what the cabinet sends ------------------------------------------------


class ConnectIn(Camel):
    api_key: str = Field(
        max_length=API_KEY_MAX, description="From ads.openai.com → Settings."
    )


class SwitchIn(Camel):
    level: Pressable
    id: str
    wanted: Literal["pause", "resume"]


class BudgetIn(Camel):
    id: str = Field(description="The campaign's id: OpenAI keeps budgets on campaigns.")
    budget: Money


class ArchiveIn(Camel):
    level: Pressable
    id: str


class DraftIn(Camel):
    target_url: str = Field("", max_length=2048)


class NewCampaignIn(Camel):
    name: str = Field(max_length=CAMPAIGN_NAME_MAX)
    daily_budget: Money
    title: str = Field(description="3-50 characters.")
    body: str = Field(description="Up to 100 characters.")
    target_url: str
    countries: list[str] = Field(default_factory=list, description="ISO codes: UZ, KZ.")
    place_ids: list[str] = Field(
        default_factory=list, description="Ids from `GET /chatgpt/places`."
    )
    context_hints: list[str] = Field(default_factory=list)
    max_bid: Money | None = Field(
        None, description="A fixed bid per click; none lets OpenAI bid."
    )
    file_id: str = Field("", description="From `POST /chatgpt/images`.")
    image_url: str = Field("", description="A public picture, instead of `fileId`.")
    start_active: bool = True
    request_id: str = Field(
        "",
        max_length=64,
        description="The same id on a repeated press makes no second campaign.",
    )


# -- what it reads ---------------------------------------------------------


class Said(Camel):
    message: str


class Pressed(Camel):
    message: str
    dry_run: bool = Field(description="Rehearsed: nothing was sent to OpenAI.")


class ShownAccount(Camel):
    id: str
    name: str
    currency: str
    timezone: str


class Card(Camel):
    available: bool = Field(description="ChatGPT Ads is switched on for this owner.")
    connected: bool
    account: ShownAccount | None = None
    dry_run: bool
    key_help_url: str = "https://ads.openai.com/settings"


class Issue(Camel):
    code: str
    label: str


class Figures(Camel):
    spend: Money
    impressions: int
    clicks: int
    conversions: int
    ctr: Decimal | None = Field(description="Clicks per hundred impressions.")
    cpc: Money | None


class CampaignOut(Camel):
    id: str
    name: str
    delivery: Status
    raw_status: str
    issues: list[Issue]
    bidding: str
    daily_budget: Money | None
    spend_cap: Money | None
    figures: Figures


class AdOut(Camel):
    id: str
    name: str
    delivery: Status
    review_status: str
    issues: list[Issue]
    title: str
    body: str
    target_url: str
    image_url: str
    figures: Figures


class GroupOut(Camel):
    id: str
    name: str
    delivery: Status
    issues: list[Issue]
    context_hints: list[str]
    strategy: str
    figures: Figures
    ads: list[AdOut]


class ScreenAccount(ShownAccount):
    status: str
    review_status: str
    review_label: str


class ScreenOut(Camel):
    account: ScreenAccount
    period: Literal["today", "7", "30"]
    since: date
    until: date
    totals: Figures
    campaigns: list[CampaignOut]
    dry_run: bool


class DetailOut(Camel):
    period: Literal["today", "7", "30"]
    since: date
    until: date
    campaign: CampaignOut
    groups: list[GroupOut]


class PlaceOut(Camel):
    id: str
    name: str
    canonical_name: str
    type: str
    country_code: str


class ImageOut(Camel):
    file_id: str = Field(description="Empty while rehearsing: the launch goes without.")
    dry_run: bool


class DraftOut(Camel):
    titles: list[str]
    bodies: list[str]
    context_hints: list[str]


class CreatedOut(Camel):
    message: str
    dry_run: bool
    campaign_id: str
    ad_group_id: str
    ad_id: str
    review_status: str
    active: bool
    sent: dict[str, Any] = Field(
        default_factory=dict, description="While rehearsing: what would have gone."
    )


# -- building them ---------------------------------------------------------


def minor_of(amount: Money, *, currency: str) -> int:
    """An amount the cabinet sent, in the account currency's minor units."""
    whole = Decimal(amount.minor).scaleb(-amount.exponent)
    return int(ISO_MONEY.to_minor(amount=whole, currency=currency))


def shown_account(account: AdAccount) -> ShownAccount:
    return ShownAccount(
        id=account.external_id,
        name=account.name,
        currency=account.currency,
        timezone=account.timezone,
    )


def issues_of(codes: Any) -> list[Issue]:
    return [
        Issue(code=issue.code, label=ISSUE_LABELS.get(issue.code, issue.code))
        for issue in codes
    ]


def figures_of(found: Totals, *, currency: str) -> Figures:
    ctr = (
        (Decimal(found.clicks) * 100 / found.impressions).quantize(Decimal("0.01"))
        if found.impressions
        else None
    )
    cpc = found.spend_minor // found.clicks if found.clicks else None
    return Figures(
        spend=zero_or(found.spend_minor, currency, provider=PROVIDER),
        impressions=found.impressions,
        clicks=found.clicks,
        conversions=found.conversions,
        ctr=ctr,
        cpc=money(cpc, currency, provider=PROVIDER),
    )


def campaign_out(campaign: Any, found: Totals, *, currency: str) -> CampaignOut:
    return CampaignOut(
        id=campaign.ref.id,
        name=campaign.name,
        delivery=status_word(campaign.delivery),
        raw_status=campaign.status,
        issues=issues_of(campaign.issues),
        bidding=campaign.objective_raw,
        daily_budget=money(campaign.daily_budget_minor, currency, provider=PROVIDER),
        spend_cap=money(campaign.spend_cap_minor, currency, provider=PROVIDER),
        figures=figures_of(found, currency=currency),
    )


def screen_out(screen: Screen, *, dry_run: bool) -> ScreenOut:
    currency = screen.info.currency
    return ScreenOut(
        account=ScreenAccount(
            id=screen.info.id,
            name=screen.info.name,
            currency=currency,
            timezone=screen.info.timezone,
            status=screen.info.status,
            review_status=screen.info.review_status,
            review_label=REVIEW_LABELS.get(screen.info.review_status, ""),
        ),
        period=screen.period.key,  # type: ignore[arg-type]
        since=screen.period.since,
        until=screen.period.until,
        totals=figures_of(screen.totals, currency=currency),
        campaigns=[
            campaign_out(campaign, found, currency=currency)
            for campaign, found in screen.campaigns
        ],
        dry_run=dry_run,
    )


def detail_out(detail: CampaignDetail) -> DetailOut:
    currency = detail.account.currency
    return DetailOut(
        period=detail.period.key,  # type: ignore[arg-type]
        since=detail.period.since,
        until=detail.period.until,
        campaign=campaign_out(detail.campaign, detail.figures, currency=currency),
        groups=[
            GroupOut(
                id=group.ref.id,
                name=group.name,
                delivery=status_word(group.delivery),
                issues=issues_of(group.issues),
                context_hints=list(group.targeting_raw.get("context_hints", [])),
                strategy=group.optimization_goal_raw,
                figures=figures_of(figures, currency=currency),
                ads=[
                    AdOut(
                        id=ad.ref.id,
                        name=ad.name,
                        delivery=status_word(ad.delivery),
                        review_status=ad.effective_status,
                        issues=issues_of(ad.issues),
                        title=ad.creative.headline if ad.creative else "",
                        body=ad.creative.message if ad.creative else "",
                        target_url=ad.creative.link_url if ad.creative else "",
                        image_url=ad.creative.thumbnail_url if ad.creative else "",
                        figures=figures_of(ad_figures, currency=currency),
                    )
                    for ad, ad_figures in ads
                ],
            )
            for group, figures, ads in detail.groups
        ],
    )


def place_out(place: PlaceInfo) -> PlaceOut:
    return PlaceOut(
        id=place.id,
        name=place.name,
        canonical_name=place.canonical_name,
        type=place.type,
        country_code=place.country_code,
    )


def created_out(created: Created) -> CreatedOut:
    message = (
        "Sinov rejimi: kampaniya ChatGPT Ads'ga yuborilmadi."
        if created.dry_run
        else "Kampaniya yaratildi. Reklama OpenAI tekshiruvidan o'tgach ko'rsatiladi."
    )
    return CreatedOut(
        message=message,
        dry_run=created.dry_run,
        campaign_id=created.campaign_id,
        ad_group_id=created.ad_group_id,
        ad_id=created.ad_id,
        review_status=created.review_status,
        active=created.active,
        sent=created.sent,
    )


__all__ = [
    "ArchiveIn",
    "BudgetIn",
    "Card",
    "ConnectIn",
    "CreatedOut",
    "DetailOut",
    "DraftIn",
    "DraftOut",
    "ImageOut",
    "NewCampaignIn",
    "PlaceOut",
    "Pressed",
    "Said",
    "ScreenOut",
    "SwitchIn",
]
