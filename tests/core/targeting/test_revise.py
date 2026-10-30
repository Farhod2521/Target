"""Changing part of a running audience without losing the rest.

The provider takes a targeting spec whole - there is no call that widens a
radius, only one that replaces the audience - so an absent key means
"remove this" rather than "leave this alone". A dialog that edits four
fields of a document with twenty keys has exactly one safe shape, and most
of what is pinned here is that shape: everything not named survives.

The rest is the distinction between "not asked" and "no constraint", which
is the one a careless reading collapses - and collapsing it is how a
campaign aimed at three cities becomes a campaign aimed at a circle.
"""

from typing import Any

import pytest

from core.targeting import AudienceEdit, changed, revise, revised
from core.targeting.exceptions import InvalidTargeting

AROUND: dict[str, Any] = {
    "geo_locations": {
        "custom_locations": [
            {
                "latitude": "41.31",
                "longitude": "69.24",
                "radius": 5,
                "distance_unit": "kilometer",
            }
        ]
    },
    "age_min": 25,
    "age_max": 45,
    "genders": [2],
    "flexible_spec": [{"interests": [{"id": "1"}, {"id": "2"}]}],
    "publisher_platforms": ["facebook", "instagram"],
    "custom_audiences": [{"id": "900"}],
    "excluded_custom_audiences": [{"id": "901"}],
    "targeting_automation": {"advantage_audience": 0},
    "locales": [6],
}

CITIES: dict[str, Any] = {
    "geo_locations": {"cities": [{"key": "2172"}, {"key": "2173"}]},
    "age_min": 18,
    "age_max": 65,
}


# --- The whole point: what was not named survives ------------------------
def test_everything_the_edit_does_not_name_comes_through_untouched() -> None:
    """The keys below are the ones a writer built from a sketch would drop,
    and each of them is somebody's money: saved audiences, exclusions, the
    placement list and the automation switch."""
    after = revise(AROUND, edit=AudienceEdit(age_min=30, age_max=40))

    for key in (
        "publisher_platforms",
        "custom_audiences",
        "excluded_custom_audiences",
        "targeting_automation",
        "locales",
        "flexible_spec",
    ):
        assert after[key] == AROUND[key]


def test_the_stored_spec_is_not_written_through() -> None:
    """The mirror row this came from is the row the undo is photographed
    from. A shallow copy would edit it in place."""
    before = {"geo_locations": {"custom_locations": [{"radius": 5}]}}

    revise(before, edit=AudienceEdit(radius_km=20))

    assert before["geo_locations"]["custom_locations"][0]["radius"] == 5


def test_an_empty_spec_is_refused_rather_than_invented() -> None:
    """No document to copy is an audience nobody can put back afterwards."""
    with pytest.raises(InvalidTargeting):
        revise({}, edit=AudienceEdit(age_min=25, age_max=45))


# --- Ages ----------------------------------------------------------------
def test_both_ends_of_the_age_range_move_together() -> None:
    after = revise(AROUND, edit=AudienceEdit(age_min=30, age_max=55))

    assert (after["age_min"], after["age_max"]) == (30, 55)


def test_an_age_range_with_one_end_is_refused() -> None:
    """A missing age_max is sixty-five to the provider, which is a different
    question from the one that was asked."""
    with pytest.raises(InvalidTargeting):
        revise(AROUND, edit=AudienceEdit(age_min=30))


def test_an_upside_down_age_range_is_refused() -> None:
    with pytest.raises(InvalidTargeting):
        revise(AROUND, edit=AudienceEdit(age_min=50, age_max=30))


def test_an_unasked_age_leaves_the_stored_one_alone() -> None:
    after = revise(AROUND, edit=AudienceEdit(radius_km=10))

    assert (after["age_min"], after["age_max"]) == (25, 45)


# --- Genders -------------------------------------------------------------
def test_everybody_is_written_as_no_key_at_all() -> None:
    """An absent genders and an empty list mean the same thing to the
    provider, and sending the empty list is an error on some fields."""
    after = revise(AROUND, edit=AudienceEdit(genders=()))

    assert "genders" not in after


def test_naming_both_genders_is_everybody_said_the_long_way() -> None:
    after = revise(AROUND, edit=AudienceEdit(genders=(1, 2)))

    assert "genders" not in after


def test_one_gender_is_written_as_the_providers_own_number() -> None:
    after = revise(AROUND, edit=AudienceEdit(genders=(1,)))

    assert after["genders"] == [1]


def test_an_unasked_gender_leaves_the_stored_one_alone() -> None:
    """`None` is "not asked" and `()` is "everybody" - collapsing the two
    would widen an audience nobody widened."""
    after = revise(AROUND, edit=AudienceEdit(age_min=30, age_max=40))

    assert after["genders"] == [2]


# --- Radius --------------------------------------------------------------
def test_the_radius_is_written_where_a_real_spec_keeps_it() -> None:
    after = revise(AROUND, edit=AudienceEdit(radius_km=25))

    assert after["geo_locations"]["custom_locations"][0]["radius"] == 25


def test_an_audience_that_is_a_list_of_cities_grows_no_circle() -> None:
    """A delivery service covering Tashkent is not "within N km of"
    anything, and a radius written for it misses half the districts."""
    after = revise(CITIES, edit=AudienceEdit(radius_km=25))

    assert after == CITIES


def test_a_radius_written_in_another_unit_is_left_alone() -> None:
    """Rewriting a number whose unit we did not check is how an ad set ends
    up advertising to a neighbouring country."""
    spec = {
        "geo_locations": {"custom_locations": [{"radius": 5, "distance_unit": "mile"}]}
    }

    after = revise(spec, edit=AudienceEdit(radius_km=25))

    assert after["geo_locations"]["custom_locations"][0]["radius"] == 5


def test_a_radius_of_nothing_is_refused() -> None:
    with pytest.raises(InvalidTargeting):
        revise(AROUND, edit=AudienceEdit(radius_km=0))


# --- Interests -----------------------------------------------------------
def test_interests_are_removed_whole_when_that_is_what_was_asked() -> None:
    """The blocks are an OR of ANDs, so taking one row out of one block
    changes what the other rows mean."""
    after = revise(AROUND, edit=AudienceEdit(keep_interests=False))

    assert "flexible_spec" not in after


def test_keeping_interests_is_the_default_and_changes_nothing() -> None:
    after = revise(AROUND, edit=AudienceEdit())

    assert after == AROUND


# --- Whether anything moved ---------------------------------------------
def test_an_edit_that_matches_what_is_stored_moved_nothing() -> None:
    """A spec replaced with itself is an audit row claiming a change nobody
    made - and a fresh learning phase paid for in exchange for nothing."""
    assert not changed(AROUND, edit=AudienceEdit(age_min=25, age_max=45))


def test_an_edit_that_moves_one_field_counts_as_a_change() -> None:
    assert changed(AROUND, edit=AudienceEdit(age_min=25, age_max=46))


def test_asking_for_everybody_where_one_gender_is_stored_is_a_change() -> None:
    assert changed(AROUND, edit=AudienceEdit(genders=()))


def test_an_empty_edit_names_nothing() -> None:
    assert AudienceEdit().is_empty
    assert not AudienceEdit(radius_km=5).is_empty
    assert not AudienceEdit(keep_interests=False).is_empty


# --- The launch's own rules, on a running audience -------------------------
AUTOMATIC: dict[str, Any] = {
    "geo_locations": {"countries": ["UZ"]},
    "age_min": 20,
    "targeting_automation": {"advantage_audience": 1},
}


def test_an_automatic_audience_gets_no_upper_age() -> None:
    """Advantage+ takes no age_max below sixty-five: sent anyway, Meta refuses
    the write after the screen has already said it went."""
    after, notes = revised(AUTOMATIC, edit=AudienceEdit(age_min=22, age_max=40))

    assert "age_max" not in after
    assert after["age_min"] == 22
    assert [note.field for note in notes] == ["age_max"]


def test_an_automatic_audience_starts_no_later_than_twenty_five() -> None:
    after, notes = revised(AUTOMATIC, edit=AudienceEdit(age_min=30, age_max=65))

    assert after["age_min"] == 25
    assert [(note.field, note.reason) for note in notes] == [
        ("age_min", "automatic_targeting")
    ]


def test_a_special_category_keeps_every_age_and_both_genders() -> None:
    """Housing, jobs and credit may not be narrowed by age or gender."""
    spec = {**CITIES, "age_min": 18, "age_max": 65}

    after, notes = revised(
        spec,
        edit=AudienceEdit(age_min=25, age_max=40, genders=(2,)),
        special=True,
    )

    assert after == spec
    assert {note.field for note in notes} == {"age", "genders"}


def test_a_special_category_circle_is_never_smaller_than_the_law_allows() -> None:
    after, notes = revised(AROUND, edit=AudienceEdit(radius_km=5), special=True)

    assert after["geo_locations"]["custom_locations"][0]["radius"] == 24
    assert [note.field for note in notes] == ["radius"]


def test_a_gender_that_is_not_a_gender_is_refused_not_widened() -> None:
    """Dropping an unknown number left nothing, and nothing meant everybody."""
    with pytest.raises(InvalidTargeting):
        revise(AROUND, edit=AudienceEdit(genders=(3,)))


def test_the_dialogs_own_defaults_sent_back_move_nothing() -> None:
    """A spec with no ages is 18-65 to Meta; the dialog shows those and
    sends them back untouched - that is no change, not a write."""
    spec = {"geo_locations": {"countries": ["UZ"]}}

    assert not changed(spec, edit=AudienceEdit(age_min=18, age_max=65))
    assert not changed(AUTOMATIC, edit=AudienceEdit(age_min=20, age_max=65))
