"""Changing what already runs: a switch, a budget, a removal."""

from typing import Any, Final

from adskit.errors import InvalidRequest
from adskit.money import ISO_MONEY
from adskit.refs import ExternalRef, MinorUnits

from googleadskit.client import AdsClient
from googleadskit.resources import collection_of, customer_of, quoted

SETTABLE: Final[dict[str, str]] = {"active": "ENABLED", "paused": "PAUSED"}

_MICROS_PLACES: Final = 6


def change_status(
    client: AdsClient, ref: ExternalRef, *, status: str, validate_only: bool
) -> dict[str, Any]:
    """Pause or enable one object. Sending it twice is harmless."""
    google_status = SETTABLE.get(status)
    if google_status is None:
        raise InvalidRequest(f"google cannot be asked for status {status!r}")
    return _mutate(
        client,
        ref,
        {
            "update": {"resourceName": ref.id, "status": google_status},
            "updateMask": "status",
        },
        validate_only=validate_only,
    )


def change_budget(
    client: AdsClient,
    ref: ExternalRef,
    *,
    daily_budget_minor: MinorUnits,
    validate_only: bool,
) -> dict[str, Any]:
    """Set the daily amount on the budget this campaign draws on."""
    if ref.level != "campaign":
        raise InvalidRequest("google keeps a budget on the campaign only")
    query = (
        "SELECT campaign_budget.resource_name, customer.currency_code "
        f"FROM campaign WHERE campaign.resource_name = '{quoted(ref.id)}'"
    )
    rows = list(client.search(customer_of(ref.id), query))
    budget = (
        str(rows[0].get("campaignBudget", {}).get("resourceName") or "") if rows else ""
    )
    if not budget:
        raise InvalidRequest(f"google has no budget for {ref.id}")
    currency = str(rows[0].get("customer", {}).get("currencyCode") or "")
    places = ISO_MONEY.decimal_places(currency)
    body = {
        "operations": [
            {
                "update": {
                    "resourceName": budget,
                    "amountMicros": str(
                        int(daily_budget_minor) * 10 ** (_MICROS_PLACES - places)
                    ),
                },
                "updateMask": "amountMicros",
            }
        ],
        "validateOnly": validate_only,
    }
    return client.post(f"customers/{customer_of(ref.id)}/campaignBudgets:mutate", body)


def remove(
    client: AdsClient, ref: ExternalRef, *, validate_only: bool
) -> dict[str, Any]:
    """Remove one object for good."""
    return _mutate(client, ref, {"remove": ref.id}, validate_only=validate_only)


def _mutate(
    client: AdsClient,
    ref: ExternalRef,
    operation: dict[str, Any],
    *,
    validate_only: bool,
) -> dict[str, Any]:
    path = f"customers/{customer_of(ref.id)}/{collection_of(ref.id)}:mutate"
    return client.post(path, {"operations": [operation], "validateOnly": validate_only})


__all__ = ["SETTABLE", "change_budget", "change_status", "remove"]
