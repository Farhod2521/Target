"""Which Google Ads accounts a person's grant reaches.

Google answers the question in three parts.
``listAccessibleCustomers`` names every account the person can open
directly, and only by resource name; a GAQL query per account then says
what each one is. Accounts the person reaches only through a manager are
not in that list: ``customer_client`` on the manager names them, direct and
indirect alike, and each is then reached with the manager's id in
``login-customer-id``.

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

# Every level under the manager at once. A manager inside it cannot advertise,
# and a closed account has nothing to show.
_CLIENTS_QUERY: Final = (
    "SELECT customer_client.id, customer_client.descriptive_name, "
    "customer_client.currency_code, customer_client.time_zone, "
    "customer_client.manager, customer_client.test_account, "
    "customer_client.status FROM customer_client "
    "WHERE customer_client.manager = false "
    "AND customer_client.status = 'ENABLED'"
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


def clients_of(client: AdsClient, manager_id: str) -> list[CustomerDTO]:
    """The accounts that advertise under one manager, reached through it."""
    rows = client.through(manager_id).search(manager_id, _CLIENTS_QUERY)
    found: list[CustomerDTO] = []
    for row in rows:
        customer = row.get("customerClient", {})
        found.append(
            CustomerDTO(
                id=str(customer.get("id") or ""),
                name=str(customer.get("descriptiveName") or ""),
                currency=str(customer.get("currencyCode") or ""),
                time_zone=str(customer.get("timeZone") or ""),
                is_manager=bool(customer.get("manager")),
                is_test=bool(customer.get("testAccount")),
                status=str(customer.get("status") or ""),
                login_customer_id=manager_id,
            )
        )
    return found


def list_accounts(client: AdsClient) -> list[CustomerDTO]:
    """Every account the grant reaches, directly or through a manager.

    An account Google lists but will not describe - cancelled, closed, or
    never set up - is left out rather than failing the whole list: one dead
    account from years ago must not stop somebody connecting the live one.
    Any other refusal still raises, because it says something about the
    grant rather than about one account.

    An account the person can open directly stays direct even when a manager
    holds it too: that road needs no manager to stay linked.
    """
    accounts: dict[str, CustomerDTO] = {}
    for customer_id in list_customer_ids(client):
        try:
            found = describe_customer(client, customer_id)
        except GoogleAdsAPIError as exc:
            if exc.has("authorizationError", *_UNQUERYABLE):
                continue
            raise
        accounts[found.id] = found
    for manager in [row for row in accounts.values() if _opens_clients(row)]:
        try:
            clients = clients_of(client, manager.id)
        except GoogleAdsAPIError as exc:
            if exc.has("authorizationError", *_UNQUERYABLE):
                continue
            raise
        for found in clients:
            accounts.setdefault(found.id, found)
    return list(accounts.values())


def _opens_clients(customer: CustomerDTO) -> bool:
    return customer.is_manager and customer.status == "ENABLED"


__all__ = ["clients_of", "describe_customer", "list_accounts", "list_customer_ids"]
