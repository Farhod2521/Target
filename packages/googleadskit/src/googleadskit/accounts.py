"""Which Google Ads accounts a person's grant reaches.

Two calls, because Google answers the question in two halves.
``listAccessibleCustomers`` names every account the person can open
directly, and only by resource name; a GAQL query per account then says
what each one is. Accounts under a manager the person can reach only
through that manager are not in the first list - reaching them needs the
manager's id in ``login-customer-id``, which is a later step.

These functions raise :mod:`googleadskit.errors`; the adapter is what turns
those into the domain's errors, as it does for every other call.
"""

from typing import Any, Final

from googleadskit.client import AdsClient
from googleadskit.dto import CustomerDTO
from googleadskit.errors import GoogleAdsAPIError

_RESOURCE_PREFIX: Final = "customers/"

_CUSTOMER_QUERY: Final = (
    "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
    "customer.time_zone, customer.manager, customer.test_account, "
    "customer.status FROM customer LIMIT 1"
)

# What Google answers when the account is listed but can no longer be
# queried: cancelled, closed, or never finished signing up.
_UNQUERYABLE: Final = ("CUSTOMER_NOT_ENABLED", "INCOMPLETE_SIGNUP")


def list_customer_ids(client: AdsClient) -> list[str]:
    """Ids of every account the grant reaches directly, in Google's order."""
    answer = client.get("customers:listAccessibleCustomers")
    names = answer.get("resourceNames") or []
    return [
        str(name)[len(_RESOURCE_PREFIX) :]
        for name in names
        if str(name).startswith(_RESOURCE_PREFIX)
    ]


def describe_customer(client: AdsClient, customer_id: str) -> CustomerDTO:
    """Name, currency, time zone and state of one account."""
    rows = list(client.search(customer_id, _CUSTOMER_QUERY))
    customer: dict[str, Any] = rows[0].get("customer", {}) if rows else {}
    return CustomerDTO(
        id=str(customer.get("id") or customer_id),
        name=str(customer.get("descriptiveName") or ""),
        currency=str(customer.get("currencyCode") or ""),
        time_zone=str(customer.get("timeZone") or ""),
        is_manager=bool(customer.get("manager")),
        is_test=bool(customer.get("testAccount")),
        status=str(customer.get("status") or ""),
    )


def list_accounts(client: AdsClient) -> list[CustomerDTO]:
    """Every directly reachable account, described.

    An account Google lists but will not describe - cancelled, closed, or
    never set up - is left out rather than failing the whole list: one dead
    account from years ago must not stop somebody connecting the live one.
    Any other refusal still raises, because it says something about the
    grant rather than about one account.
    """
    accounts: list[CustomerDTO] = []
    for customer_id in list_customer_ids(client):
        try:
            accounts.append(describe_customer(client, customer_id))
        except GoogleAdsAPIError as exc:
            if exc.has("authorizationError", *_UNQUERYABLE):
                continue
            raise
    return accounts


__all__ = ["describe_customer", "list_accounts", "list_customer_ids"]
