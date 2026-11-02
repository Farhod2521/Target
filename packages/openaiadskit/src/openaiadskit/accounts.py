"""The one ad account an API key opens, and the places it can target."""

from dataclasses import dataclass

from openaiadskit.client import AdsClient


@dataclass(frozen=True, slots=True)
class AdAccountInfo:
    """``GET /ad_account``: what a key is for, read when it is connected.

    ``review_status`` is OpenAI's brand review (``in_review``, ``rejected``,
    ``approved``): nothing serves until it is approved.
    """

    id: str
    name: str
    url: str
    status: str
    timezone: str
    currency: str
    review_status: str


@dataclass(frozen=True, slots=True)
class PlaceInfo:
    """One ``geo_lookup`` answer: a market or region to target by ``id``."""

    id: str
    name: str
    canonical_name: str
    type: str
    country_code: str


def read_ad_account(client: AdsClient) -> AdAccountInfo:
    found = client.get("ad_account")
    review = found.get("review")
    return AdAccountInfo(
        id=str(found.get("id") or ""),
        name=str(found.get("name") or found.get("account_name") or ""),
        url=str(found.get("url") or ""),
        status=str(found.get("status") or ""),
        timezone=str(found.get("timezone") or "UTC"),
        currency=str(found.get("currency_code") or "USD").upper(),
        review_status=str(review.get("status") or "")
        if isinstance(review, dict)
        else "",
    )


def search_places(client: AdsClient, *, query: str, limit: int = 20) -> list[PlaceInfo]:
    found = client.get("geo_lookup/search", {"q": query, "limit": limit})
    return [
        PlaceInfo(
            id=str(row.get("id") or ""),
            name=str(row.get("name") or ""),
            canonical_name=str(row.get("canonical_name") or row.get("name") or ""),
            type=str(row.get("type") or ""),
            country_code=str(row.get("country_code") or ""),
        )
        for row in found.get("results") or []
        if isinstance(row, dict) and row.get("id")
    ]


__all__ = ["AdAccountInfo", "PlaceInfo", "read_ad_account", "search_places"]
