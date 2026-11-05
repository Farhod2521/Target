"""Google's rows as the domain's DTOs, and its statuses in the domain's words.

The reading half of the adapter, apart from the port class so that each
stays a size somebody can read. Nothing here calls Google.
"""

from decimal import Decimal
from typing import Any, Final

from adskit.dto import (
    AdDTO,
    AdSetDTO,
    CampaignDTO,
    IssueDTO,
    RecommendationDTO,
    ReviewFeedbackDTO,
)
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

# An ad's policy review. A refusal stops it; the narrowed approvals let it
# serve to fewer people, which the owner should hear but is not a refusal.
DISAPPROVED: Final = "DISAPPROVED"
_NARROWED: Final = frozenset({"APPROVED_LIMITED", "AREA_OF_INTEREST_ONLY"})
# The kinds of finding that hold an ad back. DESCRIPTIVE and BROADENING
# only describe it and are left out.
_HOLDING: Final = frozenset(
    {"PROHIBITED", "LIMITED", "FULLY_LIMITED", "AREA_OF_INTEREST_ONLY"}
)

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
    policy = node.get("policySummary") or {}
    approval = str(policy.get("approvalStatus") or "")
    findings = [
        entry
        for entry in policy.get("policyTopicEntries") or ()
        if isinstance(entry, dict) and entry.get("topic")
    ]
    refused = approval == DISAPPROVED
    return AdDTO(
        ref=_ref("ad", str(node.get("resourceName") or "")),
        adset_ref=_ref("adset", str(row.get("adGroup", {}).get("resourceName") or "")),
        # Most Google ad types carry no name; the type stands in.
        name=str(ad.get("name") or ad.get("type") or ""),
        status=status,
        effective_status=primary,
        # A paused ad stays paused: its refusal is said, not its delivery.
        delivery="rejected"
        if refused and status != "PAUSED"
        else delivery_of(status=status, primary_status=primary),
        issues=_narrowings(findings) if approval in _NARROWED else (),
        # ``None`` when Google named no policy: an empty mapping would read
        # downstream as a refusal with words.
        review_feedback=ReviewFeedbackDTO(
            overall={str(entry["topic"]): _finding(entry) for entry in findings}
        )
        if refused and findings
        else None,
    )


def _finding(entry: dict[str, Any]) -> str:
    """Google's kind of finding, then the words it caught, if it quoted any."""
    caught = _evidence(entry.get("evidences") or ())
    kind = str(entry.get("type") or "")
    return " — ".join(part for part in (kind, "; ".join(caught)) if part)


def _evidence(evidences: Any) -> list[str]:
    """The quoted text, sites and broken addresses, as Google lists them."""
    found: list[str] = []
    for evidence in evidences:
        if not isinstance(evidence, dict):
            continue
        found += evidence.get("textList", {}).get("texts", ())
        found += evidence.get("websiteList", {}).get("websites", ())
        found += evidence.get("destinationTextList", {}).get("destinationTexts", ())
        broken = evidence.get("destinationNotWorking") or {}
        if broken.get("expandedUrl"):
            code = broken.get("httpErrorCode") or broken.get("dnsErrorType") or ""
            found.append(f"{broken['expandedUrl']} {code}".strip())
    return [str(item) for item in found if item]


def _narrowings(findings: list[dict[str, Any]]) -> tuple[IssueDTO, ...]:
    """An approval that narrows who sees the ad, one issue per policy."""
    return tuple(
        IssueDTO(
            code=str(entry["topic"])[:32],
            summary=str(entry["topic"]),
            message=_finding(entry),
            level="ad",
            kind=str(entry.get("type") or ""),
        )
        for entry in findings
        if str(entry.get("type") or "") in _HOLDING
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
    "DISAPPROVED",
    "ad_dto",
    "campaign_dto",
    "delivery_of",
    "group_dto",
    "micros_to_minor",
    "node_key",
]
