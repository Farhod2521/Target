"""Turning a typed place name into something Meta will target.

Two halves. The call - what is asked for and what is not - and the reading
of the answer, which is where the decisions live: what kind of place this
is, whether a radius may be drawn around it, and which of several rows an
advertiser in one country is most likely to have meant.

No live calls. Every response here is one this endpoint really sends.
"""

from typing import Any
from unittest.mock import patch

import httpx
from adskit import ExternalRef
from metaads.adapter import MetaAudiences
from metaads.client import GraphClient
from metaads.discovery import search_locations

TASHKENT = {
    "key": "2420901",
    "name": "Tashkent",
    "type": "city",
    "country_code": "UZ",
    "country_name": "Uzbekistan",
    "region": "Toshkent Shahri",
    "region_id": 3847,
    "supports_region": True,
    "supports_city": True,
}
TASHKENT_KZ = {
    "key": "2510990",
    "name": "Tashkent",
    "type": "city",
    "country_code": "KZ",
    "country_name": "Kazakhstan",
    "region": "Turkistan",
}
REGION = {
    "key": "3847",
    "name": "Toshkent Shahri",
    "type": "region",
    "country_code": "UZ",
    "country_name": "Uzbekistan",
}


def answering(payload: dict) -> GraphClient:
    return GraphClient(
        token="t",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
    )


def recording(payload: dict) -> tuple[GraphClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    return (
        GraphClient(
            token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
        seen,
    )


def found(rows: list[dict[str, Any]], *, country: str = "UZ") -> list:
    with patch("metaads.adapter.GraphClient", return_value=answering({"data": rows})):
        return MetaAudiences().find_locations(
            query="Tashkent", country_code=country, token="t"
        )


# --- The call ------------------------------------------------------------
def test_only_the_three_grains_a_campaign_is_ever_aimed_at_are_asked_for() -> None:
    """Meta also answers zip codes, neighborhoods and media markets. A
    picker full of rows an owner has to rule out one by one is worse than a
    shorter list, and no preset targets at that grain."""
    graph, seen = recording({"data": []})

    search_locations(query="Tashkent", token="t", client=graph)

    url = str(seen[0].url)
    assert "adgeolocation" in url
    for grain in ("city", "region", "country"):
        assert grain in url
    assert "zip" not in url


def test_the_key_is_asked_for_by_name() -> None:
    """This endpoint's default answer is a name and a type. A caller that
    needs the key in order to target anything gets a row it must discard."""
    graph, seen = recording({"data": []})

    search_locations(query="Tashkent", token="t", client=graph)

    assert "key" in str(seen[0].url)


def test_a_blank_query_is_not_a_round_trip() -> None:
    """Asking a provider what it has under nothing is not a question."""
    with patch("metaads.adapter.GraphClient", side_effect=AssertionError("called")):
        assert (
            MetaAudiences().find_locations(query="  ", country_code="UZ", token="t")
            == []
        )


# --- Reading the answer --------------------------------------------------
def test_a_city_comes_back_as_something_targetable() -> None:
    place = found([TASHKENT])[0]

    assert place.ref == ExternalRef(provider="meta", level="location", id="2420901")
    assert place.name == "Tashkent"
    assert place.kind == "city"
    assert place.country_code == "UZ"


def test_a_city_carries_its_region_so_two_of_them_can_be_told_apart() -> None:
    """ "Toshkent" is a city and the region around it. A person choosing
    between two rows with the same word on them is guessing."""
    assert found([TASHKENT])[0].context == "Toshkent Shahri"


def test_a_city_carries_its_regions_key_and_a_region_carries_none() -> None:
    """The key, not the name, is what tells a city and its own region apart:
    Meta refuses the two sent together."""
    city, region = found([TASHKENT, REGION])
    assert city.parent_id == "3847"
    assert region.parent_id == ""


def test_a_region_falls_back_to_its_country_for_the_same_reason() -> None:
    assert found([REGION])[0].context == "Uzbekistan"


def test_a_radius_is_offered_around_a_city_and_not_around_a_region() -> None:
    """Meta accepts a radius on a region entry and then ignores it. The ad
    set is created, delivers to the whole region, and the number the owner
    typed appears nowhere."""
    city, region = found([TASHKENT, REGION])

    assert city.supports_radius
    assert not region.supports_radius


def test_a_kind_this_product_does_not_model_stays_unmodelled() -> None:
    """Filing a zip code as a city would send it in the cities array, where
    Meta drops it silently."""
    row = {"key": "700000", "name": "700000", "type": "zip", "country_code": "UZ"}

    assert found([row])[0].kind == "other"
    assert not found([row])[0].supports_radius


# --- Which one they meant ------------------------------------------------
def test_the_advertisers_own_country_is_offered_first() -> None:
    """There is a Tashkent in Kazakhstan too, and Meta ranks by fame."""
    places = found([TASHKENT_KZ, TASHKENT], country="UZ")

    assert [place.country_code for place in places] == ["UZ", "KZ"]


def test_the_other_country_is_kept_rather_than_filtered_out() -> None:
    """A shop near a border advertises across it, and the row somebody
    actually meant is sometimes the foreign one."""
    assert len(found([TASHKENT_KZ, TASHKENT], country="UZ")) == 2


def test_an_unlabelled_row_does_not_sink() -> None:
    """A row with no country is Meta being terse, not a place somewhere
    else, and pushing it to the bottom hides it behind the noise."""
    terse = {"key": "9", "name": "Tashkent", "type": "city"}

    assert found([terse], country="")[0].ref.id == "9"
