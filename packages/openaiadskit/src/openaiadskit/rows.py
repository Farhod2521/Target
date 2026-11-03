"""OpenAI's campaign, ad group and ad objects as the domain's DTOs.

**Delivery** is read from the object's ``status`` and its
``serving_issues``, OpenAI's own list of why something is not serving.
Several issues can stand at once; the one an advertiser must act on first
wins: money, then a refusal, then an end, then a parent switched off, then
a wait. An issue whose code begins ``partial_serving_`` means some of it is
serving, which is delivery.

**Money** arrives in micros (millionths of the account currency) on
budgets and bids, and as a decimal in reports.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

from adskit.dto import AdDTO, AdSetDTO, CampaignDTO, CreativeDTO, IssueDTO
from adskit.money import ISO_MONEY
from adskit.refs import Delivery, ExternalRef, Level, MinorUnits, ProviderName

PROVIDER: Final = ProviderName("chatgpt")
ARCHIVED: Final = "archived"
_MICROS_EXPONENT: Final = -6

_BILLING: Final = frozenset(
    {
        "ad_account_payment_method_missing_or_unauthorized",
        "ad_account_threshold_payment_failed",
    }
)
_REJECTED: Final = frozenset(
    {
        "ad_account_suspended",
        "ad_account_brand_review_missing_favicon",
        "ad_account_brand_review_rejected",
        "ad_account_persona_verification_not_approved",
        "ad_account_persona_verification_step_up_required",
        "review_not_approved",
        "landing_page_crawl_issue",
        "policy_country_targeting_blocked",
        "title_missing",
        "advertiser_name_missing",
        "image_or_favicon_missing",
        "target_url_invalid",
        "reserved_query_params_present",
    }
)
_FINISHED: Final = frozenset(
    {"campaign_ended", "campaign_budget_exhausted", "ad_account_budget_exhausted"}
)
_PAUSED_ABOVE: Final = frozenset({"campaign_not_active", "ad_group_not_active"})
_PENDING: Final = frozenset(
    {
        "ad_in_review",
        "ad_account_brand_review_in_progress",
        "ad_account_brand_review_escalated_review",
        "campaign_not_started",
    }
)


def delivery_of(*, status: str, issues: list[str], level: Level) -> Delivery:
    """The domain's delivery word for one object."""
    if status == "paused":
        return "paused"
    if status == ARCHIVED:
        return "finished"
    if status != "active":
        return "unknown"
    found = set(issues)
    # A campaign is never "paused_above": nothing sits above it.
    above = frozenset() if level == "campaign" else _PAUSED_ABOVE
    order: tuple[tuple[frozenset[str], Delivery], ...] = (
        (_BILLING, "billing"),
        (_REJECTED, "rejected"),
        (_FINISHED, "finished"),
        (above, "paused_above"),
        (_PENDING, "pending"),
    )
    for words, delivery in order:
        if found & words:
            return delivery
    serving = {code for code in found if not code.startswith("partial_serving_")}
    return "active" if not serving else "unknown"


def micros_to_minor(micros: object, currency: str) -> MinorUnits | None:
    """Millionths of a unit as the currency's minor units; ``None`` stays."""
    if micros is None or micros == "":
        return None
    amount = Decimal(str(micros)).scaleb(_MICROS_EXPONENT)
    return ISO_MONEY.to_minor(amount=amount, currency=currency)


def minor_to_micros(minor: int, currency: str) -> int:
    """The other way, for a write: minor units as millionths of a unit."""
    places = ISO_MONEY.decimal_places(currency)
    return int(Decimal(minor).scaleb(6 - places))


def amount_to_minor(amount: object, currency: str) -> MinorUnits:
    """A report's decimal spend as minor units."""
    return ISO_MONEY.to_minor(amount=Decimal(str(amount or 0)), currency=currency)


def ref(level: Level, object_id: str) -> ExternalRef:
    return ExternalRef(provider=PROVIDER, level=level, id=object_id)


def issue_codes(item: dict[str, Any]) -> list[str]:
    return [
        str(issue.get("code"))
        for issue in item.get("serving_issues") or []
        if isinstance(issue, dict) and issue.get("code")
    ]


def _issues(codes: list[str]) -> tuple[IssueDTO, ...]:
    return tuple(IssueDTO(code=code, summary=code) for code in codes)


def _when(seconds: object) -> datetime | None:
    if not isinstance(seconds, int | float) or not seconds:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)


def campaign_dto(item: dict[str, Any], *, currency: str) -> CampaignDTO:
    status = str(item.get("status") or "")
    codes = issue_codes(item)
    budget = item.get("budget") or {}
    return CampaignDTO(
        ref=ref("campaign", str(item["id"])),
        name=str(item.get("name") or ""),
        status=status,
        effective_status=codes[0] if codes else status,
        delivery=delivery_of(status=status, issues=codes, level="campaign"),
        objective_raw=str(item.get("objective") or item.get("bidding_type") or ""),
        daily_budget_minor=micros_to_minor(
            budget.get("daily_spend_limit_micros"), currency
        ),
        spend_cap_minor=micros_to_minor(
            budget.get("lifetime_spend_limit_micros"), currency
        ),
        currency=currency,
        created_time=_when(item.get("created_at")),
        issues=_issues(codes),
    )


def group_dto(item: dict[str, Any], *, campaign_id: str, currency: str) -> AdSetDTO:
    """``campaign_id`` is the caller's: an ad group's answer does not carry it."""
    status = str(item.get("status") or "")
    codes = issue_codes(item)
    bidding = item.get("bidding_config") or {}
    return AdSetDTO(
        ref=ref("adset", str(item["id"])),
        campaign_ref=ref("campaign", campaign_id),
        name=str(item.get("name") or ""),
        status=status,
        effective_status=codes[0] if codes else status,
        delivery=delivery_of(status=status, issues=codes, level="adset"),
        optimization_goal_raw=str(bidding.get("strategy") or ""),
        billing_event_raw=str(bidding.get("billing_event_type") or ""),
        currency=currency,
        targeting_raw={"context_hints": list(item.get("context_hints") or [])},
        issues=_issues(codes),
    )


def ad_dto(item: dict[str, Any], *, ad_group_id: str) -> AdDTO:
    """``ad_group_id`` is the caller's: an ad's answer does not carry it."""
    status = str(item.get("status") or "")
    codes = issue_codes(item)
    creative = item.get("creative") or {}
    ad_id = str(item["id"])
    return AdDTO(
        ref=ref("ad", ad_id),
        adset_ref=ref("adset", ad_group_id),
        name=str(item.get("name") or ""),
        status=status,
        effective_status=str(item.get("review_status") or status),
        delivery=delivery_of(status=status, issues=codes, level="ad"),
        creative=CreativeDTO(
            ref=ref("creative", ad_id),
            kind=str(creative.get("type") or ""),
            headline=str(creative.get("title") or ""),
            message=str(creative.get("body") or ""),
            link_url=str(creative.get("target_url") or ""),
            thumbnail_url=str(creative.get("image_url") or ""),
        ),
        issues=_issues(codes),
    )


@dataclass(frozen=True, slots=True)
class Place:
    id: str
    # Empty when OpenAI echoes only the id.
    name: str = ""


@dataclass(frozen=True, slots=True)
class Locations:
    """Where a campaign runs: whole countries and chosen places.

    Read back in the same two halves ``launch.campaign_body`` writes, so a
    copy of a campaign can be sent again as it is.
    """

    countries: tuple[str, ...] = ()
    places: tuple[Place, ...] = ()


def locations_of(item: dict[str, Any]) -> Locations:
    targeting = item.get("targeting") or {}
    found = targeting.get("locations") if isinstance(targeting, dict) else None
    if not isinstance(found, dict):
        return Locations()
    places = []
    for row in found.get("include") or ():
        if isinstance(row, dict) and row.get("id"):
            name = row.get("canonical_name") or row.get("name") or ""
            places.append(Place(id=str(row["id"]), name=str(name)))
        elif isinstance(row, str | int) and str(row):
            places.append(Place(id=str(row)))
    return Locations(
        countries=tuple(str(code) for code in found.get("countries") or () if code),
        places=tuple(places),
    )


__all__ = [
    "ARCHIVED",
    "PROVIDER",
    "Locations",
    "Place",
    "ad_dto",
    "amount_to_minor",
    "campaign_dto",
    "delivery_of",
    "group_dto",
    "issue_codes",
    "locations_of",
    "micros_to_minor",
    "minor_to_micros",
    "ref",
]
