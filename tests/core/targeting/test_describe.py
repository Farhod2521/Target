"""Reading a finished spec back into four facts.

No database, no provider, no clock - a mapping in and a value out, which
is the whole reason this reader lives in ``core``.

Two things are being pinned here. The obvious one is that a well-formed
spec is read correctly. The one that matters more is that a malformed one
still is: every document reaching this reader came from a provider or from
a row somebody edited by hand, and a screen that raised on one bad key
would show nothing about an audience that is otherwise perfectly readable.
"""

from typing import Any

import pytest

from core.targeting import describe
from core.targeting.describe import _PLACE_KEYS
from core.targeting.geo import _ARRAYS

AROUND: dict[str, Any] = {
    "geo_locations": {
        "custom_locations": [
            {
                "latitude": "41.311081",
                "longitude": "69.240562",
                "radius": 5,
                "distance_unit": "kilometer",
            }
        ]
    },
    "age_min": 25,
    "age_max": 45,
    "genders": [1],
    "flexible_spec": [
        {
            "interests": [{"id": "6003", "name": "Restaurants"}],
            "life_events": [{"id": "6015", "name": "Newlywed (1 year)"}],
        }
    ],
}


# --- Geography, in the three shapes a spec can carry ---------------------
def test_a_pin_and_a_radius_is_read_with_its_unit() -> None:
    sketch = describe(AROUND)

    assert sketch.geo == "around"
    assert sketch.radius == 5
    assert sketch.radius_unit == "kilometer"


def test_named_places_are_counted_and_never_named() -> None:
    """The document carries keys, not names. Counting is the honest answer."""
    sketch = describe(
        {"geo_locations": {"cities": [{"key": "2420901"}], "regions": [{"key": "38"}]}}
    )

    assert sketch.geo == "places"
    assert sketch.places == 2
    assert sketch.radius is None


def test_a_country_is_its_own_shape() -> None:
    sketch = describe({"geo_locations": {"countries": ["UZ"]}})

    assert sketch.geo == "country"
    assert sketch.places == 1


def test_a_pin_wins_over_places_because_it_is_the_tighter_statement() -> None:
    sketch = describe(
        {
            "geo_locations": {
                "custom_locations": [{"radius": 3, "distance_unit": "kilometer"}],
                "cities": [{"key": "2420901"}],
            }
        }
    )

    assert sketch.geo == "around"


def test_no_geography_block_is_not_the_same_as_an_empty_one() -> None:
    """Both are "everywhere", and both have to say so rather than draw a gap."""
    assert describe({}).geo == ""
    assert describe({"geo_locations": {}}).geo == ""


def test_every_place_kind_the_builder_writes_is_counted() -> None:
    """Guards the seam between this reader and ``geo._ARRAYS``.

    A fourth kind added to the builder and not here would be read as no
    places at all - an audience aimed at four regions reported as aimed
    nowhere, which is the one failure mode that looks like data rather
    than like a bug.
    """
    written = set(_ARRAYS.values()) - {"countries"}

    assert written <= set(_PLACE_KEYS)


# --- Demographics --------------------------------------------------------
def test_ages_come_through_as_numbers() -> None:
    sketch = describe(AROUND)

    assert (sketch.age_min, sketch.age_max) == (25, 45)


def test_ages_written_as_strings_are_read() -> None:
    """Meta answers with strings on some reads and integers on others."""
    sketch = describe({"age_min": "18", "age_max": "65"})

    assert (sketch.age_min, sketch.age_max) == (18, 65)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([1], "male"),
        ([2], "female"),
        ([1, 2], ""),
        ([], ""),
        (None, ""),
    ],
)
def test_both_genders_is_everybody_and_reads_as_no_filter(
    value: Any, expected: str
) -> None:
    """Three inputs, one meaning.

    Printing "erkaklar va ayollar" for ``[1, 2]`` would show a filter the
    owner never set as though they had.
    """
    assert describe({"genders": value}).genders == expected


# --- Detailed targeting --------------------------------------------------
def test_interests_behaviours_and_life_events_are_counted_together() -> None:
    """Three catalogues, one question: how specific is this audience."""
    assert describe(AROUND).interests == 2


def test_several_blocks_are_summed_rather_than_read_from_the_first() -> None:
    """This product writes one block; Ads Manager can write several."""
    sketch = describe(
        {
            "flexible_spec": [
                {"interests": [{"id": "1"}, {"id": "2"}]},
                {"behaviors": [{"id": "3"}]},
            ]
        }
    )

    assert sketch.interests == 3


# --- The owner's own lists, and the provider's own widening --------------
def test_saved_lists_are_reported_as_present_rather_than_counted() -> None:
    sketch = describe(
        {
            "custom_audiences": [{"id": "23"}],
            "excluded_custom_audiences": [{"id": "24"}],
        }
    )

    assert sketch.uses_own_lists is True
    assert sketch.excludes_own_lists is True


def test_automatic_widening_is_read_because_it_changes_the_other_answers() -> None:
    sketch = describe({"targeting_automation": {"advantage_audience": 1}})

    assert sketch.is_automatic is True
    assert describe({"targeting_automation": {}}).is_automatic is False


# --- Nothing readable ----------------------------------------------------
def test_an_empty_spec_says_so_instead_of_drawing_blank_fields() -> None:
    assert describe({}).is_empty is True


def test_a_spec_of_keys_nobody_reads_here_is_also_empty() -> None:
    """Placements are real targeting and are not part of this sketch."""
    assert describe({"publisher_platforms": ["facebook"]}).is_empty is True


def test_one_readable_key_is_enough_to_stop_being_empty() -> None:
    assert describe({"age_min": 25}).is_empty is False


# --- Malformed input, which is the case that has to survive --------------
@pytest.mark.parametrize(
    "spec",
    [
        {"geo_locations": "Toshkent"},
        {"geo_locations": {"custom_locations": "5 km"}},
        {"flexible_spec": {"interests": [{"id": "1"}]}},
        {"flexible_spec": ["not a block"]},
        {"genders": "male"},
    ],
)
def test_a_malformed_key_is_dropped_and_never_raises(spec: dict[str, Any]) -> None:
    """A screen showing nothing is worse than a screen showing three of four."""
    describe(spec)


def test_a_bad_age_does_not_take_the_rest_of_the_sketch_with_it() -> None:
    sketch = describe({"age_min": "yigirma besh", "age_max": 45, "genders": [2]})

    assert sketch.age_min is None
    assert sketch.age_max == 45
    assert sketch.genders == "female"


def test_a_boolean_age_is_refused_rather_than_read_as_one() -> None:
    """``True`` is an ``int`` in Python and would render as the age 1."""
    assert describe({"age_min": True}).age_min is None


def test_something_that_is_not_a_mapping_at_all_is_an_empty_sketch() -> None:
    assert describe([]).is_empty is True
