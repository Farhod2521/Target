"""Structural validation: correct what can be corrected, refuse the rest.

Most of this file is about the difference between the two. Widening a
radius from 200 km to 80 is not a reason to stop the wizard - the owner
gets told and the campaign runs. Spending below the account's floor is,
because the provider would reject the campaign after it was created.
"""

import pytest

from core.targeting import (
    BuiltTargeting,
    validate_launchable,
    validate_structure,
)
from core.targeting.exceptions import (
    BudgetTooLow,
    InvalidTargeting,
    NoInterestsChosen,
)

BASE = {
    "age_min": 25,
    "age_max": 45,
    "genders": [1],
    "geo_locations": {
        "custom_locations": [{"radius": 5, "distance_unit": "kilometer"}]
    },
    "publisher_platforms": ["facebook", "instagram"],
    "instagram_positions": ["stream", "reels"],
    "flexible_spec": [{"interests": [{"id": "1", "name": "Restaurants"}]}],
}


def _validated(spec: dict, **kwargs: object) -> tuple[dict, tuple]:
    """``validate_structure`` with the audience mode pinned to ``interests``.

    These cases are about ages, radii, empty values and Special Ad
    Categories - the corrections the validator makes on its own. The
    default mode is ``automatic``, which removes ``age_max`` and reports
    it, so an unpinned call would add one adjustment to every assertion in
    this file and hide the one being tested behind it.

    The mode's own corrections have their own file, and the two places
    where this one exercises the default pass it explicitly.
    """
    kwargs.setdefault("targeting_mode", "interests")
    return validate_structure(spec, **kwargs)  # type: ignore[arg-type]


def _radius(spec: dict[str, object]) -> int:
    geo = spec["geo_locations"]
    assert isinstance(geo, dict)
    return int(geo["custom_locations"][0]["radius"])


def _reasons(notes: tuple[object, ...]) -> set[str]:
    return {n.reason for n in notes}  # type: ignore[attr-defined]


def test_a_clean_spec_comes_back_unchanged_and_unremarked() -> None:
    spec, notes = _validated(BASE)

    assert notes == ()
    assert spec["age_min"] == 25


def test_the_input_is_not_mutated() -> None:
    """A validator that edits its argument is a bug nobody sees until later."""
    validate_structure(BASE)

    assert _radius(dict(BASE)) == 5


def test_an_age_below_the_floor_is_raised_and_reported() -> None:
    spec, notes = _validated({**BASE, "age_min": 14})

    assert spec["age_min"] == 18
    assert _reasons(notes) == {"age_out_of_range"}


def test_an_age_above_the_ceiling_is_lowered() -> None:
    spec, _ = _validated({**BASE, "age_max": 90})

    assert spec["age_max"] == 65


def test_a_minimum_above_its_maximum_is_refused() -> None:
    """Nothing to correct: any guess here targets people nobody chose."""
    with pytest.raises(InvalidTargeting):
        validate_structure({**BASE, "age_min": 50, "age_max": 30})


def test_a_preset_with_no_age_keeps_none() -> None:
    """18-65 means the same thing, but reports a change nobody made."""
    spec, notes = _validated(
        {"geo_locations": {"countries": ["UZ"]}, "publisher_platforms": ["facebook"]}
    )

    assert "age_min" not in spec
    assert notes == ()


def test_a_radius_beyond_the_limit_is_pulled_back() -> None:
    spec, notes = _validated(
        {**BASE, "geo_locations": {"custom_locations": [{"radius": 200}]}}
    )

    assert _radius(spec) == 80
    assert _reasons(notes) == {"radius_out_of_range"}


def test_a_radius_of_zero_becomes_the_smallest_the_provider_takes() -> None:
    spec, _ = _validated(
        {**BASE, "geo_locations": {"custom_locations": [{"radius": 0}]}}
    )

    assert _radius(spec) == 1


def test_the_placement_block_is_written_here_and_not_read_from_the_spec() -> None:
    """Whatever came in, the whole block is replaced.

    Where the ad appears is one answer with two states and it is not
    carried in the spec, so a stale key from a preset or an old draft is
    overwritten rather than merged with. See
    ``tests/core/targeting/test_placements.py``.
    """
    stale = {**BASE, "instagram_positions": ["stream", "explore_home"]}

    spec, notes = _validated(stale, placement_mode="standard")

    assert spec["instagram_positions"] == ["stream", "story", "reels"]
    assert notes == ()

    # And in the other direction, which is the default: replaced by
    # nothing at all rather than left behind. One stale key is what opts an
    # ad set back out of Advantage+ placements.
    spec, notes = _validated(stale)

    assert "instagram_positions" not in spec
    assert notes == ()


def test_a_special_ad_category_removes_who_the_audience_is() -> None:
    """Housing, employment and credit ads may not choose by person."""
    spec, notes = _validated(BASE, special_ad_category="HOUSING")

    assert "genders" not in spec
    assert "flexible_spec" not in spec
    assert _reasons(notes) == {"special_ad_category"}


def test_a_special_ad_category_opens_the_age_range_fully() -> None:
    spec, _ = _validated(BASE, special_ad_category="EMPLOYMENT")

    assert (spec["age_min"], spec["age_max"]) == (18, 65)


def test_a_special_ad_category_widens_a_tight_radius() -> None:
    spec, _ = _validated(BASE, special_ad_category="CREDIT")

    assert _radius(spec) == 24


def test_the_category_that_forbade_a_field_travels_with_the_note() -> None:
    _, notes = _validated(BASE, special_ad_category="HOUSING")

    assert all(n.detail == "HOUSING" for n in notes if n.field == "genders")  # type: ignore[attr-defined]


def test_a_budget_below_the_account_floor_is_refused() -> None:
    with pytest.raises(BudgetTooLow) as caught:
        validate_structure(
            BASE, daily_budget_minor=500, min_daily_minor=2000, currency="USD"
        )

    assert caught.value.given_minor == 500
    assert caught.value.minimum_minor == 2000
    assert caught.value.currency == "USD"


def test_an_unknown_floor_does_not_block_anything() -> None:
    """Zero means nobody read it from the account yet.

    A made-up minimum would refuse real campaigns for a number we invented,
    and the provider publishes a different one per currency and account.
    """
    spec, _ = _validated(BASE, daily_budget_minor=1, min_daily_minor=0)

    assert spec


def test_empty_values_are_dropped_without_comment() -> None:
    """An absent ``genders`` and an empty one mean the same thing: everyone."""
    spec, notes = _validated({**BASE, "genders": []})

    assert "genders" not in spec
    assert notes == ()


def _built(**overrides: object) -> BuiltTargeting:
    fields: dict[str, object] = {
        "objective": "OUTCOME_LEADS",
        "optimization_goal": "LEAD_GENERATION",
        "billing_event": "IMPRESSIONS",
        "destination_type": "ON_AD",
        "sends_to": "form",
        "call_to_action": "SIGN_UP",
        "targeting": {"age_min": 25},
        "daily_budget_minor": 1000,
        "currency": "USD",
        "special_ad_categories": (),
        "preset_key": "restaurant/leads",
        "preset_version": "1",
        # Pinned. The gate below only requires an interest in this mode -
        # see ``requires_interests`` - and it is not the default, so a
        # fixture taking the default would assert nothing here.
        "targeting_mode": "interests",
    }
    return BuiltTargeting(**{**fields, **overrides})  # type: ignore[arg-type]


def test_launching_without_a_confirmed_interest_is_refused() -> None:
    """The product rule: the audience is never nobody in particular."""
    with pytest.raises(NoInterestsChosen):
        validate_launchable(_built())


def test_launching_with_a_confirmed_interest_is_allowed() -> None:
    built = _built(targeting={"flexible_spec": [{"interests": [{"id": "1"}]}]})

    validate_launchable(built)


def test_a_special_ad_category_is_exempt_from_the_interest_rule() -> None:
    """It is not allowed to have interests at all, so it cannot be missing one."""
    validate_launchable(_built(special_ad_categories=("HOUSING",)))
