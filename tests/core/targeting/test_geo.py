"""Where a campaign is aimed, as a value.

The rules that decide what a geography answer means, tested without a
database, a provider or a clock - which is the whole reason they live in
``core`` rather than in the service that fills them in.
"""

import pytest

from core.targeting import GeoChoice, GeoPlace, fallback, geo_locations
from core.targeting.exceptions import InvalidTargeting

TASHKENT = GeoPlace(key="2420901", name="Tashkent", kind="city")
REGION = GeoPlace(key="3847", name="Toshkent Shahri", kind="region")


# --- What each mode sends ------------------------------------------------
def test_a_pin_and_a_radius_become_a_custom_location() -> None:
    spec = geo_locations(
        GeoChoice(mode="around", lat="41.311081", lng="69.240562", radius_km=5)
    )

    assert spec == {
        "custom_locations": [
            {
                "latitude": "41.311081",
                "longitude": "69.240562",
                "radius": 5,
                "distance_unit": "kilometer",
            }
        ]
    }


def test_chosen_places_are_split_by_what_they_are() -> None:
    """A city sent among the regions is accepted, ignored, and delivers to
    the wrong outline - which looks like the campaign working."""
    spec = geo_locations(
        GeoChoice(mode="places", places=(TASHKENT, REGION), origin="chosen")
    )

    assert spec == {
        "cities": [{"key": "2420901"}],
        "regions": [{"key": "3847"}],
    }


def test_a_city_inside_a_chosen_region_is_not_sent_beside_it() -> None:
    """Meta refuses the pair - "some locations conflict with each other" -
    and the region already covers everybody in the city."""
    inside = GeoPlace(key="2420901", name="Tashkent", kind="city", parent="3847")
    spec = geo_locations(
        GeoChoice(mode="places", places=(inside, REGION), origin="chosen")
    )

    assert spec == {"regions": [{"key": "3847"}]}


def test_a_city_in_another_region_is_kept() -> None:
    elsewhere = GeoPlace(key="2420901", name="Tashkent", kind="city", parent="9999")
    spec = geo_locations(
        GeoChoice(mode="places", places=(elsewhere, REGION), origin="chosen")
    )

    assert spec == {"cities": [{"key": "2420901"}], "regions": [{"key": "3847"}]}


def test_the_same_place_twice_is_sent_once() -> None:
    spec = geo_locations(
        GeoChoice(mode="places", places=(TASHKENT, TASHKENT), origin="chosen")
    )

    assert spec == {"cities": [{"key": "2420901"}]}


def test_choosing_a_city_sends_no_radius() -> None:
    """The delivery service case. A radius measured from a city centre cuts
    off the districts it delivers to, which is worse than no radius."""
    spec = geo_locations(
        GeoChoice(mode="places", places=(TASHKENT,), radius_km=5, origin="chosen")
    )

    assert "radius" not in str(spec)


def test_a_country_is_one_code() -> None:
    assert geo_locations(fallback(country_code="UZ")) == {"countries": ["UZ"]}


# --- What cannot be sent -------------------------------------------------
def test_a_radius_with_no_pin_is_refused() -> None:
    """Not widened silently. The caller has a fallback to reach for, and
    quietly targeting a country from a mode that meant "around the shop"
    would spend a city's budget on a country."""
    with pytest.raises(InvalidTargeting):
        geo_locations(GeoChoice(mode="around", radius_km=5))


def test_half_a_pin_is_no_pin() -> None:
    """A latitude alone is a point on the prime meridian."""
    assert not GeoChoice(mode="around", lat="41.31", radius_km=5).has_pin


def test_a_pin_beside_zero_zero_is_no_pin() -> None:
    """Open sea for a degree in every direction: the centre of a map nobody
    moved, or a field read as zero - never a shop."""
    stray = GeoChoice(mode="around", lat="-0.003225", lng="-0.641071", radius_km=30)
    kampala = GeoChoice(mode="around", lat="0.347596", lng="32.582520", radius_km=5)

    assert not stray.has_pin
    assert kampala.has_pin


def test_a_pin_with_no_radius_is_refused() -> None:
    with pytest.raises(InvalidTargeting):
        geo_locations(GeoChoice(mode="around", lat="41.31", lng="69.24"))


def test_places_with_nothing_in_them_is_refused() -> None:
    with pytest.raises(InvalidTargeting):
        geo_locations(GeoChoice(mode="places", origin="chosen"))


def test_a_place_the_provider_never_confirmed_does_not_count() -> None:
    """A key is what targets. A name that never resolved is a word, and a
    spec built from it would carry an empty list - which targets nobody on
    Meta and everybody in the reading of it."""
    unresolved = GeoPlace(key="", name="Samarqand", kind="city")

    with pytest.raises(InvalidTargeting):
        geo_locations(GeoChoice(mode="places", places=(unresolved,)))


def test_an_unresolved_name_is_kept_beside_the_ones_that_worked() -> None:
    """Dropped from the spec, not from the record. The screen has to be
    able to say which name it could not find."""
    choice = GeoChoice(
        mode="places",
        places=(TASHKENT, GeoPlace(key="", name="Samarqand")),
        origin="chosen",
    )

    assert len(choice.places) == 2
    assert geo_locations(choice) == {"cities": [{"key": "2420901"}]}


# --- Whether to say we widened it ----------------------------------------
def test_a_country_nobody_asked_for_is_reported() -> None:
    assert fallback(country_code="UZ").widened


def test_a_country_somebody_chose_is_not() -> None:
    """Telling an owner their audience was widened, about a decision they
    made on purpose, is describing them back to themselves."""
    chosen = GeoChoice(mode="country", country_code="UZ", origin="chosen")

    assert not chosen.widened


def test_a_chosen_city_is_never_a_widening() -> None:
    assert not GeoChoice(mode="places", places=(TASHKENT,), origin="chosen").widened
