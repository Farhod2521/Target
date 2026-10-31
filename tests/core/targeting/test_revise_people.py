"""A running audience changed by who it reaches, and nothing else with it."""

import pytest

from core.targeting.audiences import AudienceRef
from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import GeoPlace
from core.targeting.revise import (
    AudienceEdit,
    Detail,
    detail_is_open,
    detailed_of,
    excluded_detailed_of,
    excluded_places_of,
    only_place_moved,
    revise,
    revised,
)

SPEC = {
    "geo_locations": {"cities": [{"key": "1"}], "location_types": ["home"]},
    "age_min": 25,
    "flexible_spec": [
        {
            "interests": [{"id": "10", "name": "Tort"}],
            "behaviors": [{"id": "20", "name": "Sayohatchi"}],
            "industries": [{"id": "30", "name": "IT"}],
        }
    ],
    "exclusions": {"interests": [{"id": "40", "name": "Ovqat"}]},
    "custom_audiences": [{"id": "50"}],
}
COFFEE = Detail(id="11", name="Coffee", kind="interests")
WEDDING = Detail(id="21", name="To'y", kind="life_events")


def test_rows_read_back_with_their_own_key() -> None:
    assert detailed_of(SPEC) == (
        Detail(id="10", name="Tort", kind="interests"),
        Detail(id="20", name="Sayohatchi", kind="behaviors"),
        Detail(id="30", name="IT", kind="industries"),
    )
    assert excluded_detailed_of(SPEC) == (
        Detail(id="40", name="Ovqat", kind="interests"),
    )


def test_detail_is_replaced_under_each_rows_key() -> None:
    found = revise(SPEC, edit=AudienceEdit(detailed=(COFFEE, WEDDING)))

    assert found["flexible_spec"] == [
        {
            "interests": [{"id": "11", "name": "Coffee"}],
            "life_events": [{"id": "21", "name": "To'y"}],
        }
    ]
    assert found["exclusions"] == SPEC["exclusions"]
    assert found["age_min"] == 25


def test_no_detail_left_removes_the_block() -> None:
    assert "flexible_spec" not in revise(SPEC, edit=AudienceEdit(detailed=()))


def test_several_blocks_cannot_be_rewritten() -> None:
    both = {**SPEC, "flexible_spec": [{"interests": [{"id": "1"}]}, {"behaviors": []}]}

    assert detail_is_open(SPEC) is True
    assert detail_is_open(both) is False
    with pytest.raises(InvalidTargeting):
        revise(both, edit=AudienceEdit(detailed=(COFFEE,)))


def test_exclusions_are_replaced_and_keep_what_is_not_detail() -> None:
    spec = {**SPEC, "exclusions": {"interests": [{"id": "40"}], "custom": 1}}

    found = revise(spec, edit=AudienceEdit(excluded_detailed=(WEDDING,)))

    assert found["exclusions"] == {
        "custom": 1,
        "life_events": [{"id": "21", "name": "To'y"}],
    }


def test_no_exclusions_left_removes_the_key() -> None:
    assert "exclusions" not in revise(SPEC, edit=AudienceEdit(excluded_detailed=()))


def test_own_lists_are_written_on_both_sides() -> None:
    found = revise(
        SPEC,
        edit=AudienceEdit(
            included_lists=(AudienceRef(external_id="51"),),
            excluded_lists=(AudienceRef(external_id="52"),),
        ),
    )

    assert found["custom_audiences"] == [{"id": "51"}]
    assert found["excluded_custom_audiences"] == [{"id": "52"}]


def test_a_list_named_on_both_sides_is_only_excluded_and_said() -> None:
    same = AudienceRef(external_id="51", label="Mijozlar")

    found, notes = revised(
        SPEC, edit=AudienceEdit(included_lists=(same,), excluded_lists=(same,))
    )

    assert "custom_audiences" not in found
    assert found["excluded_custom_audiences"] == [{"id": "51"}]
    assert [note.reason for note in notes] == ["audience_on_both_sides"]


def test_one_side_named_leaves_the_other_alone() -> None:
    spec = {**SPEC, "excluded_custom_audiences": [{"id": "52"}]}

    found = revise(spec, edit=AudienceEdit(included_lists=()))

    assert "custom_audiences" not in found
    assert found["excluded_custom_audiences"] == [{"id": "52"}]


def test_languages_are_replaced_and_can_be_cleared() -> None:
    spec = {**SPEC, "locales": [6]}

    assert revise(spec, edit=AudienceEdit(locales=(24, 28)))["locales"] == [24, 28]
    assert "locales" not in revise(spec, edit=AudienceEdit(locales=()))


def test_excluded_places_are_replaced_and_can_be_cleared() -> None:
    place = GeoPlace(key="7", name="Samarqand", kind="city")

    found = revise(SPEC, edit=AudienceEdit(excluded_places=(place,)))

    assert found["excluded_geo_locations"] == {"cities": [{"key": "7"}]}
    assert excluded_places_of(found) == (
        GeoPlace(key="7", name="7", kind="city"),
    )
    assert "excluded_geo_locations" not in revise(
        found, edit=AudienceEdit(excluded_places=())
    )


def test_an_excluded_place_is_not_a_place_move() -> None:
    place = GeoPlace(key="7", name="Samarqand", kind="city")

    moved = revise(SPEC, edit=AudienceEdit(excluded_places=(place,)))

    assert only_place_moved(SPEC, moved) is False


def test_a_pin_replaces_the_places_and_keeps_the_block_settings() -> None:
    found = revise(
        SPEC, edit=AudienceEdit(pin=("41.3", "69.2"), radius_km=8)
    )

    assert found["geo_locations"] == {
        "custom_locations": [
            {
                "latitude": "41.3",
                "longitude": "69.2",
                "radius": 8,
                "distance_unit": "kilometer",
            }
        ],
        "location_types": ["home"],
    }
    assert only_place_moved(SPEC, found) is True


def test_a_pin_keeps_the_radius_it_already_had() -> None:
    spec = {
        "geo_locations": {
            "custom_locations": [
                {
                    "latitude": "1.5",
                    "longitude": "2.5",
                    "radius": 12,
                    "distance_unit": "kilometer",
                }
            ]
        }
    }

    found = revise(spec, edit=AudienceEdit(pin=("41.3", "69.2")))

    assert found["geo_locations"]["custom_locations"][0]["radius"] == 12
    assert found["geo_locations"]["custom_locations"][0]["latitude"] == "41.3"


def test_a_pin_beyond_the_rules_is_brought_inside_and_said() -> None:
    found, notes = revised(
        SPEC, edit=AudienceEdit(pin=("41.3", "69.2"), radius_km=1), special=True
    )

    assert found["geo_locations"]["custom_locations"][0]["radius"] >= 24
    assert [note.field for note in notes] == ["radius"]


def test_an_edit_of_any_new_field_is_not_empty() -> None:
    assert AudienceEdit().is_empty is True
    assert AudienceEdit(detailed=()).is_empty is False
    assert AudienceEdit(excluded_detailed=()).is_empty is False
    assert AudienceEdit(included_lists=()).is_empty is False
    assert AudienceEdit(excluded_lists=()).is_empty is False
    assert AudienceEdit(locales=()).is_empty is False
    assert AudienceEdit(excluded_places=()).is_empty is False
    assert AudienceEdit(pin=("1.5", "2.5")).is_empty is False
