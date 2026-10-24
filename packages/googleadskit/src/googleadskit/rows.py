"""Google's rows as the domain's DTOs, and its statuses in the domain's words.

The reading half of the adapter, apart from the port class so that each
stays a size somebody can read. Nothing here calls Google.
"""

from decimal import Decimal
from typing import Any, Final

from adskit.dto import AdDTO, AdSetDTO, CampaignDTO, RecommendationDTO
from adskit.money import ISO_MONEY
from adskit.refs import Delivery, ExternalRef, Level, MinorUnits, ProviderName

PROVIDER: Final = ProviderName("google")

# Google's primary status in the domain's words. Anything Google adds
# later reads as "unknown" rather than a guess.
_PRIMARY: Final[dict[str, Delivery]] = {
    "ELIGIBLE": "active",
    "LIMITED": "active",
    "LEARNING": "active",
    "PAUSED": "paused",
    "PENDING": "pending",
    "ENDED": "finished",
    "REMOVED": "finished",
    "NOT_ELIGIBLE": "rejected",
    "MISCONFIGURED": "rejected",
}

# Google's word for a campaign held back by its budget, carried as advice:
# the campaign serves, and could serve more.
BUDGET_CONSTRAINED: Final = "BUDGET_CONSTRAINED"

_MICROS_EXPONENT: Final = -6


def delivery_of(*, status: str, primary_status: str) -> Delivery:
    """``primary_status`` in domain words, with "paused from above" told apart."""
    if status == "PAUSED":
        return "paused"
    delivery = _PRIMARY.get(primary_status, "unknown")
    if delivery == "paused" and status == "ENABLED":
        return "paused_above"
    return delivery


def micros_to_minor(micros: object, currency: str) -> MinorUnits | None:
    """Google's millionths of a unit as the currency's minor units.

    ``None`` for an absent amount - a campaign on a shared budget the
    query could not see is not a campaign with no budget.
    """
    if micros is None or micros == "":
        return None
    amount = Decimal(str(micros)).scaleb(_MICROS_EXPONENT)
    return ISO_MONEY.to_minor(amount=amount, currency=currency)


def _ref(level: Level, name: str) -> ExternalRef:
    return ExternalRef(provider=PROVIDER, level=level, id=name)


def campaign_dto(row: dict[str, Any]) -> CampaignDTO:
    node = row.get("campaign", {})
    status = str(node.get("status") or "")
    primary = str(node.get("primaryStatus") or "")
    currency = str(row.get("customer", {}).get("currencyCode") or "")
    budget = row.get("campaignBudget", {})
    return CampaignDTO(
        ref=_ref("campaign", str(node.get("resourceName") or "")),
        name=str(node.get("name") or ""),
        status=status,
        effective_status=primary,
        delivery=delivery_of(status=status, primary_status=primary),
        objective_raw=str(node.get("advertisingChannelType") or ""),
        daily_budget_minor=micros_to_minor(budget.get("amountMicros"), currency),
        shared_budget_id=(
            str(budget.get("resourceName") or "")
            if budget.get("explicitlyShared")
            else ""
        ),
        currency=currency,
        recommendations=_advice(node.get("primaryStatusReasons") or ()),
    )


def group_dto(row: dict[str, Any]) -> AdSetDTO:
    node = row.get("adGroup", {})
    status = str(node.get("status") or "")
    primary = str(node.get("primaryStatus") or "")
    return AdSetDTO(
        ref=_ref("adset", str(node.get("resourceName") or "")),
        campaign_ref=_ref(
            "campaign", str(row.get("campaign", {}).get("resourceName") or "")
        ),
        name=str(node.get("name") or ""),
        status=status,
        effective_status=primary,
        delivery=delivery_of(status=status, primary_status=primary),
        optimization_goal_raw=str(node.get("type") or ""),
    )


def ad_dto(row: dict[str, Any]) -> AdDTO:
    node = row.get("adGroupAd", {})
    ad = node.get("ad", {})
    status = str(node.get("status") or "")
    primary = str(node.get("primaryStatus") or "")
    return AdDTO(
        ref=_ref("ad", str(node.get("resourceName") or "")),
        adset_ref=_ref("adset", str(row.get("adGroup", {}).get("resourceName") or "")),
        # Most Google ad types carry no name; the type stands in.
        name=str(ad.get("name") or ad.get("type") or ""),
        status=status,
        effective_status=primary,
        delivery=delivery_of(status=status, primary_status=primary),
    )


def _advice(reasons: Any) -> tuple[RecommendationDTO, ...]:
    """The one reason Google gives that is advice rather than a fault."""
    if BUDGET_CONSTRAINED not in reasons:
        return ()
    return (
        RecommendationDTO(
            code=BUDGET_CONSTRAINED,
            title="Limited by budget",
            message="The budget is below what the campaign could spend.",
            importance="HIGH",
            blame_field="daily_budget",
        ),
    )


def node_key(resource: str) -> str:
    """``ad_group_ad`` as Google's JSON spells it: ``adGroupAd``."""
    head, *rest = resource.split("_")
    return head + "".join(part.title() for part in rest)


__all__ = [
    "BUDGET_CONSTRAINED",
    "ad_dto",
    "campaign_dto",
    "delivery_of",
    "group_dto",
    "micros_to_minor",
    "node_key",
]
