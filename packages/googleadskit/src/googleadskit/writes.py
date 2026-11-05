"""Changing what already runs: a switch, a budget, a removal.

Each is one ``:mutate`` on the object's own collection, with Google's
``validateOnly`` as the rehearsal - the request is checked in full and
nothing changes. :class:`~googleadskit.campaigns.GoogleCampaigns` holds the
port's signatures and the deployment's rehearsal switch; the requests are
built here.

**The budget is changed where it is, never swapped.** Google keeps it on a
budget object of its own, which a campaign points at. Moving the campaign to
a new budget would forget what the old one had already spent that day, and
the day could end at nearly twice the figure asked for - so the amount on
the existing budget is what changes, as Google advises. A budget shared with
other campaigns changes for all of them; the caller is told beforehand
through ``CampaignDTO.shared_budget_id``.

**A removal is final.** Google keeps a removed object's history and never
lets it run again.
"""

from datetime import date
from typing import Any, Final

from adskit.errors import InvalidRequest
from adskit.money import ISO_MONEY
from adskit.refs import ExternalRef, MinorUnits

from googleadskit.client import AdsClient
from googleadskit.resources import collection_of, customer_of, quoted

# The two states an advertiser can ask for, in Google's spelling.
SETTABLE: Final[dict[str, str]] = {"active": "ENABLED", "paused": "PAUSED"}

_MICROS_PLACES: Final = 6
_LAST_SECOND: Final = "23:59:59"


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


def change_end_date(
    client: AdsClient, ref: ExternalRef, *, end_time: str, validate_only: bool
) -> dict[str, Any]:
    """The campaign's last day, to its final second in the account's own time.

    Google takes a time of day only on some campaign types, and a Search
    campaign is not one, so the day of ``end_time`` is what is kept.
    """
    if ref.level != "campaign":
        raise InvalidRequest("google keeps an end date on the campaign only")
    try:
        day = date.fromisoformat(end_time[:10])
    except ValueError as exc:
        raise InvalidRequest(f"not a date: {end_time!r}") from exc
    return _mutate(
        client,
        ref,
        {
            "update": {
                "resourceName": ref.id,
                "endDateTime": f"{day.isoformat()} {_LAST_SECOND}",
            },
            "updateMask": "endDateTime",
        },
        validate_only=validate_only,
    )


def campaign_places(client: AdsClient, ref: ExternalRef) -> dict[str, str]:
    """The campaign's aimed-at places: geo target to its criterion's name."""
    if ref.level != "campaign":
        raise InvalidRequest("google keeps places on the campaign only")
    query = (
        "SELECT campaign_criterion.resource_name, "
        "campaign_criterion.location.geo_target_constant FROM campaign_criterion "
        f"WHERE campaign.resource_name = '{quoted(ref.id)}' "
        "AND campaign_criterion.type = 'LOCATION' "
        "AND campaign_criterion.negative = false"
    )
    found: dict[str, str] = {}
    for row in client.search(customer_of(ref.id), query):
        node = row.get("campaignCriterion", {})
        place = str((node.get("location") or {}).get("geoTargetConstant") or "")
        if place:
            found[place] = str(node.get("resourceName") or "")
    return found


def change_places(
    client: AdsClient,
    ref: ExternalRef,
    *,
    places: tuple[str, ...],
    validate_only: bool,
) -> dict[str, Any]:
    """Aim the campaign at exactly these places, in one atomic request.

    Only the difference is sent: a place that stays keeps its criterion and
    the figures under it. Nothing left would mean showing everywhere, so an
    empty list is refused rather than sent.
    """
    if not places:
        raise InvalidRequest("a google campaign must keep at least one place")
    held = campaign_places(client, ref)
    operations: list[dict[str, Any]] = [
        {"remove": criterion}
        for place, criterion in held.items()
        if place not in places
    ]
    operations += [
        {"create": {"campaign": ref.id, "location": {"geoTargetConstant": place}}}
        for place in places
        if place not in held
    ]
    if not operations:
        return {}
    return client.post(
        f"customers/{customer_of(ref.id)}/campaignCriteria:mutate",
        {"operations": operations, "validateOnly": validate_only},
    )


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


__all__ = [
    "SETTABLE",
    "campaign_places",
    "change_budget",
    "change_end_date",
    "change_places",
    "change_status",
    "remove",
]
