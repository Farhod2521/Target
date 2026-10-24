"""Google's resource names, which are the ids this package hands out."""

from typing import Final

from adskit.errors import InvalidRequest
from adskit.refs import Level

_PREFIX: Final = "customers/"

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
