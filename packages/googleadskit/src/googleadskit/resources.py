"""Google's resource names, which are the ids this package hands out.

Every Google Ads object is addressed inside one customer: a campaign id
alone does not say which account to ask, and every read and write goes to
``customers/{id}/...``. A Meta id is global, so the ports carry a bare
:class:`~adskit.refs.ExternalRef` and nothing else - and for Google that
ref must therefore carry the customer too.

So the id in a Google ref is Google's own resource name, exactly as the API
prints it: ``customers/1234567890/campaigns/111``,
``customers/1234567890/adGroups/222``,
``customers/1234567890/adGroupAds/222~333``. A mutate takes it as it is,
a GAQL filter compares against it, and nothing has to be reassembled from
parts on the way back. The account itself stays the bare customer id, the
way the account list reports it.
"""

from typing import Final

from adskit.errors import InvalidRequest
from adskit.refs import Level

_PREFIX: Final = "customers/"

# Our level name and Google's collection name for it.
COLLECTIONS: Final[dict[str, str]] = {
    "campaign": "campaigns",
    "adset": "adGroups",
    "ad": "adGroupAds",
}


def resource_name(customer_id: str, level: Level, object_id: str) -> str:
    """``customers/{customer}/{collection}/{id}`` for one of our levels."""
    collection = COLLECTIONS.get(level)
    if collection is None:
        raise InvalidRequest(f"google has no {level!r} objects to name")
    return f"{_PREFIX}{customer_id}/{collection}/{object_id}"


def customer_of(name: str) -> str:
    """The customer id a resource name lives in."""
    if not name.startswith(_PREFIX):
        raise InvalidRequest(f"not a Google Ads resource name: {name!r}")
    customer = name[len(_PREFIX) :].split("/", 1)[0]
    if not customer.isdigit():
        raise InvalidRequest(f"not a Google Ads resource name: {name!r}")
    return customer


def collection_of(name: str) -> str:
    """``campaigns`` for a campaign's name, and so on."""
    parts = name.split("/")
    if len(parts) != 4:
        raise InvalidRequest(f"not a Google Ads object name: {name!r}")
    return parts[2]


def quoted(name: str) -> str:
    """A resource name as a GAQL string literal's contents. Names hold no quotes."""
    if "'" in name or "\\" in name:
        raise InvalidRequest(f"not a Google Ads resource name: {name!r}")
    return name


__all__ = ["COLLECTIONS", "collection_of", "customer_of", "quoted", "resource_name"]
