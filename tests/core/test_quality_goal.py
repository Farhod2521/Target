"""When a lead campaign may be bought on verdicts instead of submissions.

Three conditions and the order they fail in. No database: every case is a
boolean, an integer and a provider word.

**A fourth condition sits above the three at the moment, and it fails for
everybody**: the verdicts these rules weigh are set by hand, and there is
no screen left to set one on - see ``templates/leads/partials/_live.html``.
:func:`core.targeting.quality.is_available` answers no unconditionally
while that is true, so the two cases that used to reach the quality goal
now assert that they do not. The conditions themselves are untouched and
every other case below still measures them.

The rule this file is really pinning is the last one - the owner's answer is
a condition, not a consequence. A product that upgraded a campaign because a
threshold was crossed would change what somebody's money buys without
telling them, and the change is invisible in every screen except the one
number it moves.
"""

import pytest

from core.targeting.quality import (
    MIN_QUALIFIED_FOR_QUALITY,
    QUALITY_GOAL,
    VOLUME_GOAL,
    goal_for,
    is_available,
    is_lead_goal,
    wants_quality,
)

ENOUGH = MIN_QUALIFIED_FOR_QUALITY


def asked(**overrides: object) -> str:
    """One answer, with every condition met unless a test changes it."""
    facts: dict = {
        "preset_goal": VOLUME_GOAL,
        "chosen": True,
        "reporting": True,
        "qualified_recently": ENOUGH,
    }
    return goal_for(**(facts | overrides))


def test_an_account_that_has_earned_it_is_still_bought_on_volume() -> None:
    """Every stated condition met, and the goal is unchanged.

    ``QUALITY_GOAL`` is what this asserted and what it goes back to
    asserting - see the note at the head of this file.
    """
    assert asked() == VOLUME_GOAL


def test_nobody_is_upgraded_without_asking() -> None:
    """The load-bearing case. Crossing a threshold is not permission to
    change what a campaign buys."""
    assert asked(chosen=False) == VOLUME_GOAL


def test_verdicts_going_nowhere_cannot_be_optimised_towards() -> None:
    """Without reporting, the goal names an event the provider has never
    received - which it accepts, and then under-delivers on."""
    assert asked(reporting=False) == VOLUME_GOAL


def test_too_few_verdicts_leaves_the_goal_alone() -> None:
    """An optimiser asked for a rare event it cannot find shows the ad to
    fewer people rather than to better ones."""
    assert asked(qualified_recently=ENOUGH - 1) == VOLUME_GOAL


def test_the_threshold_itself_is_not_enough_while_the_marking_is_off() -> None:
    """It was, and it is what this goes back to being.

    Reaching the threshold used to be the last condition; now the count
    cannot be added to at all, so a campaign that met every stated
    condition is still bought on volume.
    """
    assert asked(qualified_recently=ENOUGH) == VOLUME_GOAL


@pytest.mark.parametrize(
    "goal", ["QUALITY_CALL", "CONVERSATIONS", "LANDING_PAGE_VIEWS", "REACH", ""]
)
def test_only_the_form_goal_can_be_upgraded(goal: str) -> None:
    """A call campaign and a website campaign produce no lead row here for
    anybody to have judged, so there is nothing to optimise towards."""
    assert asked(preset_goal=goal) == goal


def test_a_goal_already_on_quality_is_left_alone() -> None:
    """Not an upgrade path from itself. ``is_lead_goal`` names the volume
    goal only, so an ad set already there passes through untouched."""
    assert asked(preset_goal=QUALITY_GOAL) == QUALITY_GOAL
    assert not is_lead_goal(QUALITY_GOAL)


def test_the_goal_word_is_matched_regardless_of_case() -> None:
    """It arrives from a YAML catalogue and from a provider DTO, and one of
    those two will be lower case one day."""
    assert is_lead_goal("lead_generation")


# --- The owner's own vocabulary ------------------------------------------
def test_quality_is_the_only_answer_that_asks_for_it() -> None:
    assert wants_quality("quality")


@pytest.mark.parametrize("answer", ["volume", "", "QUALITY_LEAD", "yes", "true"])
def test_anything_else_reads_as_volume(answer: str) -> None:
    """The safe direction, and the same one every other mode in this package
    falls back in: a hand-edited form cannot move a campaign onto a goal that
    changes what the money buys."""
    assert not wants_quality(answer)


def test_nothing_is_available_while_no_verdict_can_be_given() -> None:
    """The switch, and the only test that would notice it being flipped.

    Both halves were required and neither was sufficient - reporting with
    nothing to show for it is an event that has happened twice; a hundred
    verdicts with no dataset is a hundred verdicts the provider has never
    been told about. The case that satisfied both is what changed, and it
    is the first line here.
    """
    assert not is_available(reporting=True, qualified_recently=ENOUGH)
    assert not is_available(reporting=False, qualified_recently=ENOUGH)
    assert not is_available(reporting=True, qualified_recently=0)
