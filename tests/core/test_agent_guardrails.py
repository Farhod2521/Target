"""What may be done to something that is already running.

The rules here decide whether a customer's money keeps moving, and they are
the same rules for a person pressing a button and for the agent deciding at
three in the morning. Two of them are stated as much by what they refuse to
do as by what they refuse.
"""

import pytest

from core.agent import ObjectState, check_budget_change, check_status_change
from core.agent.guardrails import (
    REFUSED_ALREADY,
    REFUSED_BELOW_FLOOR,
    REFUSED_FINISHED,
    REFUSED_LEARNING,
    resets_learning,
)

RUNNING = ObjectState(delivery="active", daily_budget_minor=50_000)
LEARNING = ObjectState(delivery="active", is_learning=True, daily_budget_minor=50_000)


# --- Stopping ------------------------------------------------------------
def test_a_running_object_can_be_stopped() -> None:
    assert check_status_change(state=RUNNING, wanted="paused").allowed


def test_stopping_is_allowed_while_the_provider_is_still_learning() -> None:
    """The rule this module is most likely to be "fixed" into breaking.

    Pausing throws learning away exactly as a budget edit does. It is still
    allowed, because the thing being stopped is spending somebody's money
    and the person asking owns it - a product that answers "your ad is
    still learning" to "stop my ad" has confused spending money well with
    spending it at all.
    """
    verdict = check_status_change(state=LEARNING, wanted="paused")

    assert verdict.allowed
    assert verdict.reason == ""


def test_a_stopped_object_can_be_started() -> None:
    stopped = ObjectState(delivery="paused")

    assert check_status_change(state=stopped, wanted="active").allowed


def test_asking_for_the_state_it_is_already_in_is_refused() -> None:
    """The write would succeed and leave an audit row claiming a change
    nobody made."""
    verdict = check_status_change(state=RUNNING, wanted="active")

    assert not verdict.allowed
    assert verdict.reason == REFUSED_ALREADY


def test_something_that_ran_its_course_cannot_be_restarted() -> None:
    """Setting a completed campaign back to active succeeds at the provider
    and delivers nothing - a button that works and changes nothing."""
    finished = ObjectState(delivery="finished")

    verdict = check_status_change(state=finished, wanted="active")

    assert not verdict.allowed
    assert verdict.reason == REFUSED_FINISHED


@pytest.mark.parametrize(
    "delivery",
    [
        pytest.param("pending", id="under-review"),
        pytest.param("rejected", id="policy-problem"),
        # Nobody asked the provider, or the provider used a word we have
        # not seen. Read as permission to carry on, like every other
        # never-answered value in this codebase.
        pytest.param("unknown", id="never-answered"),
    ],
)
def test_a_state_we_did_not_choose_does_not_block_the_switch(delivery: str) -> None:
    state = ObjectState(delivery=delivery)

    assert check_status_change(state=state, wanted="paused").allowed


# --- Budget --------------------------------------------------------------
def test_a_budget_can_be_changed_on_a_settled_object() -> None:
    verdict = check_budget_change(
        state=RUNNING, wanted_minor=80_000, floor_minor=20_000
    )

    assert verdict.allowed


def test_a_budget_cannot_be_changed_while_the_provider_is_learning() -> None:
    """Unlike a pause, this buys nothing: the ad set keeps delivering
    either way, just from a worse starting point."""
    verdict = check_budget_change(
        state=LEARNING, wanted_minor=80_000, floor_minor=20_000
    )

    assert not verdict.allowed
    assert verdict.reason == REFUSED_LEARNING


def test_the_same_budget_again_is_refused() -> None:
    verdict = check_budget_change(
        state=RUNNING, wanted_minor=50_000, floor_minor=20_000
    )

    assert not verdict.allowed
    assert verdict.reason == REFUSED_ALREADY


def test_a_budget_under_the_floor_is_refused_here_not_by_the_provider() -> None:
    """The provider refuses it too, four calls later, with a message about
    a parameter."""
    verdict = check_budget_change(
        state=RUNNING, wanted_minor=10_000, floor_minor=20_000
    )

    assert not verdict.allowed
    assert verdict.reason == REFUSED_BELOW_FLOOR


def test_an_unknown_floor_switches_the_check_off_rather_than_inventing_one() -> None:
    """Zero means the account never told us. Refusing against a figure
    nobody supplied would block launches the provider would accept."""
    verdict = check_budget_change(state=RUNNING, wanted_minor=1, floor_minor=0)

    assert verdict.allowed


def test_an_object_with_no_budget_of_its_own_can_be_given_one() -> None:
    """``None`` is not zero: a campaign whose ad sets each carry a budget
    holds none itself, and that is not the same as holding nothing."""
    no_budget = ObjectState(delivery="active", daily_budget_minor=None)

    assert check_budget_change(
        state=no_budget, wanted_minor=50_000, floor_minor=20_000
    ).allowed


# --- What the screen says ------------------------------------------------
def test_the_screen_is_told_when_going_ahead_costs_the_learning() -> None:
    """A stop is allowed while learning and still throws it away. The
    person pressing deserves to know before rather than after."""
    assert resets_learning(state=LEARNING) is True
    assert resets_learning(state=RUNNING) is False


def test_a_learning_ad_set_that_never_spent_may_have_its_budget_moved() -> None:
    """Never shown, so nothing learned to lose - and a budget too small to
    win an auction is the usual reason it has not been shown."""
    state = ObjectState(
        delivery="active", is_learning=True, daily_budget_minor=1_000, has_spent=False
    )

    assert check_budget_change(state=state, wanted_minor=1_500, floor_minor=0).allowed


def test_a_learning_ad_set_that_has_spent_keeps_its_budget() -> None:
    state = ObjectState(delivery="active", is_learning=True, daily_budget_minor=1_000)

    verdict = check_budget_change(state=state, wanted_minor=1_500, floor_minor=0)

    assert verdict.reason == REFUSED_LEARNING
