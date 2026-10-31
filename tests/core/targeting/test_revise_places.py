"""A running audience moved to other places, and only that."""

import pytest

from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import GeoPlace, chosen_places
from core.targeting.revise import AudienceEdit, only_place_moved, revise

SPEC = {
    "geo_locations": {
        "countries": ["UZ"],
        "location_types": ["home", "recent"],
    },
    "age_min": 25,
    "flexible_spec": [{"interests": [{"id": "1", "name": "Tort"}]}],
}
TASHKENT = GeoPlace(key="111", name="Toshkent", kind="city")


def test_places_replace_the_block_and_nothing_else() -> None:
    found = revise(SPEC, edit=AudienceEdit(places=(TASHKENT,)))

    assert found["geo_locations"] == {
        "cities": [{"key": "111"}],
        "location_types": ["home", "recent"],
    }
    assert found["age_min"] == 25
    assert found["flexible_spec"] == SPEC["flexible_spec"]


def test_no_places_left_is_refused() -> None:
    with pytest.raises(InvalidTargeting):
        revise(SPEC, edit=AudienceEdit(places=()))


def test_a_place_move_is_told_from_any_other_change() -> None:
    moved = revise(SPEC, edit=AudienceEdit(places=(TASHKENT,)))

    assert only_place_moved(SPEC, moved) is True
    assert only_place_moved(SPEC, {**moved, "age_min": 30}) is False
    assert only_place_moved(SPEC, SPEC) is False


def test_the_places_a_spec_reads_back() -> None:
    spec = {
        "geo_locations": {
            "cities": [{"key": "111", "name": "Toshkent"}],
            "countries": ["UZ"],
        }
    }

    assert chosen_places(spec) == (
        GeoPlace(key="111", name="Toshkent", kind="city"),
        GeoPlace(key="UZ", name="UZ", kind="country"),
    )


def test_a_country_goes_as_its_bare_code_and_a_city_as_an_object() -> None:
    uzbekistan = GeoPlace(key="UZ", name="UZ", kind="country")
    almaty = GeoPlace(key="222", name="Almaty", kind="city")

    found = revise(SPEC, edit=AudienceEdit(places=(uzbekistan, almaty)))

    assert found["geo_locations"]["countries"] == ["UZ"]
    assert found["geo_locations"]["cities"] == [{"key": "222"}]
    assert {place.key for place in chosen_places(found)} == {"UZ", "222"}


def test_an_excluded_country_goes_as_its_bare_code() -> None:
    kazakhstan = GeoPlace(key="KZ", name="KZ", kind="country")

    found = revise(SPEC, edit=AudienceEdit(excluded_places=(kazakhstan,)))

    assert found["excluded_geo_locations"] == {"countries": ["KZ"]}
