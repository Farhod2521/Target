"""A running audience changed by where it is shown and by the provider's widening."""

import pytest

from core.targeting.exceptions import InvalidTargeting
from core.targeting.placements import held_mode, held_positions
from core.targeting.revise import AudienceEdit, changed, revise, revised

SPEC = {
    "geo_locations": {"countries": ["UZ"]},
    "age_min": 30,
    "age_max": 45,
    "targeting_automation": {"advantage_audience": 0},
}
ON_INSTAGRAM = {
    **SPEC,
    "publisher_platforms": ["instagram"],
    "instagram_positions": ["stream", "story"],
}


def test_a_spec_with_no_platforms_is_the_providers_choice() -> None:
    assert held_mode(SPEC) == "automatic"
    assert held_mode(ON_INSTAGRAM) == "instagram"
    assert held_mode({"publisher_platforms": ["facebook", "instagram"]}) == "standard"


def test_a_mix_from_ads_manager_is_none_of_the_modes() -> None:
    assert held_mode({"publisher_platforms": ["facebook", "messenger"]}) is None


def test_a_running_app_with_no_list_runs_everywhere() -> None:
    held = held_positions({"publisher_platforms": ["instagram"]})

    assert "ig_search" in held["instagram"] and "explore_home" in held["instagram"]
    assert held["facebook"] == ("feed", "story", "facebook_reels")


def test_the_mode_is_replaced_and_the_rest_of_the_audience_stays() -> None:
    found = revise(SPEC, edit=AudienceEdit(placement="standard"))

    assert found["publisher_platforms"] == ["facebook", "instagram"]
    assert found["facebook_positions"] == ["feed"]
    assert found["instagram_positions"] == ["stream", "story", "reels"]
    assert found["geo_locations"] == SPEC["geo_locations"]
    assert (found["age_min"], found["age_max"]) == (30, 45)


def test_an_app_that_keeps_running_keeps_its_positions() -> None:
    found = revise(ON_INSTAGRAM, edit=AudienceEdit(placement="standard"))

    assert found["instagram_positions"] == ["stream", "story"]
    assert found["facebook_positions"] == ["feed"]


def test_ticks_alone_change_the_positions_of_the_mode_it_has() -> None:
    found = revise(
        ON_INSTAGRAM, edit=AudienceEdit(positions={"instagram": ("reels", "stream")})
    )

    assert found["publisher_platforms"] == ["instagram"]
    assert found["instagram_positions"] == ["stream", "reels"]


def test_back_to_the_provider_removes_the_apps_and_keeps_the_device() -> None:
    spec = {
        **ON_INSTAGRAM,
        "device_platforms": ["mobile"],
        "audience_network_positions": ["classic"],
    }

    found = revise(spec, edit=AudienceEdit(placement="automatic"))

    assert "publisher_platforms" not in found
    assert "instagram_positions" not in found
    assert "audience_network_positions" not in found
    assert found["device_platforms"] == ["mobile"]


def test_the_same_placement_sent_back_is_no_change() -> None:
    spec = {**ON_INSTAGRAM, "instagram_positions": ["stream", "story", "shop"]}
    edit = AudienceEdit(
        placement="instagram", positions={"instagram": ("story", "stream")}
    )

    assert changed(spec, edit=edit) is False


def test_a_position_that_cannot_run_alone_is_refused() -> None:
    with pytest.raises(InvalidTargeting) as caught:
        revise(
            SPEC,
            edit=AudienceEdit(placement="facebook", positions={"facebook": ("story",)}),
        )

    assert caught.value.field == "positions"


def test_an_app_with_nothing_ticked_and_an_unknown_position_are_refused() -> None:
    for ticks in ({"instagram": ()}, {"instagram": ("billboard",)}):
        with pytest.raises(InvalidTargeting):
            revise(SPEC, edit=AudienceEdit(placement="instagram", positions=ticks))


def test_ticks_for_a_mix_of_no_mode_are_refused() -> None:
    spec = {**SPEC, "publisher_platforms": ["facebook", "messenger"]}

    with pytest.raises(InvalidTargeting):
        revise(spec, edit=AudienceEdit(positions={"facebook": ("feed",)}))
    assert revise(spec, edit=AudienceEdit(placement="facebook"))[
        "publisher_platforms"
    ] == ["facebook"]


def test_the_widening_switched_on_moves_the_ages_it_will_not_take() -> None:
    found, notes = revised(SPEC, edit=AudienceEdit(automatic=True))

    assert found["targeting_automation"] == {"advantage_audience": 1}
    assert "age_max" not in found
    assert found["age_min"] == 25
    assert {note.reason for note in notes} == {"automatic_targeting"}


def test_an_age_sent_with_the_switch_is_fitted_to_the_switch_as_it_will_be() -> None:
    found = revise(SPEC, edit=AudienceEdit(automatic=True, age_min=21, age_max=40))

    assert found["age_min"] == 21
    assert "age_max" not in found


def test_the_widening_switched_off_keeps_what_sat_beside_it() -> None:
    spec = {
        **SPEC,
        "targeting_automation": {
            "advantage_audience": 1,
            "individual_setting": {"age": 1},
        },
    }

    found = revise(spec, edit=AudienceEdit(automatic=False))

    assert found["targeting_automation"] == {
        "advantage_audience": 0,
        "individual_setting": {"age": 1},
    }


def test_the_switch_as_it_already_is_changes_nothing() -> None:
    assert changed(SPEC, edit=AudienceEdit(automatic=False)) is False


def test_a_special_category_keeps_the_widening_off() -> None:
    found, notes = revised(SPEC, edit=AudienceEdit(automatic=True), special=True)

    assert found == SPEC
    assert [note.reason for note in notes] == ["special_ad_category"]
