"""core/agent/narrow: cutting a dead slice out of an audience.

The mirror of ``test_widen``, and the tests that matter most here are the
refusals: the provider can only be told to skip a whole end of an age
range or a whole gender, so every other shape of dead cell has to come
back as nothing rather than as a change that looks right and removes the
wrong people.
"""

from typing import Any

from core.agent import narrow
from core.agent.narrow import keeps_its_audience

# The switch, off. Every spec below carries it, because a spec without it
# is one the provider may expand past - see ``keeps_its_audience``.
CHOSEN: dict[str, Any] = {"targeting_automation": {"advantage_audience": 0}}


def _spec(**overrides: Any) -> dict[str, Any]:
    return {"age_min": 18, "age_max": 65, **CHOSEN, **overrides}


# --- the automation switch is a precondition ------------------------------
def test_only_an_explicit_off_counts_as_the_advertisers_own_audience() -> None:
    """From v23.0 an omitted switch means the provider chooses, and it
    chooses on - so absence is exactly the state this cannot read."""
    assert keeps_its_audience(CHOSEN)
    assert not keeps_its_audience({})
    assert not keeps_its_audience({"targeting_automation": {"advantage_audience": 1}})
    assert not keeps_its_audience({"targeting_automation": "on"})


def test_nothing_is_proposed_where_the_provider_decides_the_audience() -> None:
    """A maximum age and a gender are suggestions it may deliver beyond, so
    narrowing either one there is a change that would be accepted, recorded
    and quietly ignored."""
    automatic = {"age_min": 18, "age_max": 65} | {
        "targeting_automation": {"advantage_audience": 1}
    }

    assert narrow(automatic, dead={"18-24|male": 90_000}, alive=["25-34|male"]) is None


# --- trimming an end of the age range -------------------------------------
def test_a_dead_youngest_band_lifts_the_floor_to_the_next_one() -> None:
    found = narrow(
        _spec(),
        dead={"18-24|male": 90_000, "18-24|female": 30_000},
        alive=["25-34|male", "35-44|female"],
    )

    assert found is not None
    assert found.step == "age"
    assert found.targeting["age_min"] == 25
    assert found.targeting["age_max"] == 65
    assert found.detail["dropped_spend_minor"] == 120_000


def test_a_dead_oldest_band_lowers_the_ceiling() -> None:
    found = narrow(
        _spec(),
        dead={"65+|male": 80_000},
        alive=["25-34|male", "35-44|female"],
    )

    assert found is not None
    assert found.step == "age"
    assert found.targeting["age_max"] == 64


def test_the_end_that_wasted_more_is_the_one_cut_first() -> None:
    """One step at a time, and the first step is the expensive one."""
    found = narrow(
        _spec(),
        dead={"18-24|male": 20_000, "65+|male": 90_000},
        alive=["25-34|male"],
    )

    assert found is not None
    assert found.detail["cut"] == "age_max"


def test_a_dead_band_in_the_middle_is_left_alone() -> None:
    """Trimming to it would take the live bands on the far side with it,
    and the provider has no way to exclude a band from the middle."""
    found = narrow(
        _spec(),
        dead={"35-44|male": 90_000, "35-44|female": 40_000},
        alive=["18-24|male", "65+|female"],
    )

    assert found is None


def test_a_band_with_one_live_cell_survives() -> None:
    """A range cannot be trimmed by gender and by age at once, so one live
    cell anywhere in the band keeps the whole band."""
    found = narrow(
        _spec(),
        dead={"18-24|male": 90_000},
        alive=["18-24|female", "25-34|male"],
    )

    assert found is None


def test_the_only_band_there_is_cannot_be_cut() -> None:
    """Cutting it leaves nobody, and a comparison that saw one band saw no
    comparison at all."""
    assert narrow(_spec(), dead={"25-34|male": 90_000}, alive=[]) is None


def test_an_unplaceable_cell_is_not_a_slice_anybody_can_skip() -> None:
    """``unknown`` is the provider's word for a person it could not place,
    not an age band with an edge."""
    found = narrow(
        _spec(),
        dead={"unknown|male": 90_000},
        alive=["25-34|male", "35-44|male"],
    )

    assert found is None


# --- dropping a gender ----------------------------------------------------
def test_a_gender_that_never_responded_is_dropped() -> None:
    found = narrow(
        _spec(),
        dead={"25-34|male": 60_000, "35-44|male": 40_000},
        alive=["25-34|female", "35-44|female"],
    )

    assert found is not None
    assert found.step == "gender"
    assert found.targeting["genders"] == [2]
    assert found.detail["dropped_gender"] == "male"
    assert found.detail["dropped_spend_minor"] == 100_000


def test_a_spec_already_aimed_at_one_gender_is_not_narrowed_again() -> None:
    """Either a change that does nothing or one that empties the audience."""
    found = narrow(
        _spec(genders=[2]),
        dead={"25-34|male": 60_000},
        alive=["25-34|female"],
    )

    assert found is None


def test_a_gender_that_converts_somewhere_is_kept() -> None:
    found = narrow(
        _spec(),
        dead={"25-34|male": 60_000},
        alive=["35-44|male", "25-34|female"],
    )

    assert found is None


def test_dropping_both_genders_is_refused() -> None:
    """It would leave nobody, which is a stopped ad set reached through the
    wrong door - the same refusal ``widen`` makes about an empty spec."""
    found = narrow(
        _spec(),
        dead={"25-34|male": 60_000, "25-34|female": 60_000},
        alive=[],
    )

    assert found is None


# --- the order of the two steps -------------------------------------------
def test_age_is_tried_before_gender() -> None:
    """Dropping a band at the end gives up a slice; dropping a gender gives
    up about half of the audience."""
    found = narrow(
        _spec(),
        dead={"18-24|male": 90_000, "25-34|male": 90_000},
        alive=["35-44|female", "25-34|female"],
    )

    assert found is not None
    assert found.step == "age"


def test_nothing_dead_is_nothing_to_do() -> None:
    assert narrow(_spec(), dead={}, alive=["25-34|male"]) is None
