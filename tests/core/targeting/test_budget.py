"""What a provider will take per day, given what the ad set optimises for.

Pure arithmetic over two numbers, and worth its own file because getting
it wrong is invisible until the second call of a creation sequence: Meta
reports one floor and enforces another, and the difference is a refusal
that names a number the account never mentioned.
"""

import inspect

import pytest

from core.targeting import daily_floor
from core.targeting.budget import RARE_EVENT_GOALS, RARE_EVENT_MULTIPLIER

# What an account reported in the production refusal this exists for:
# USD 1.00, against an enforced USD 2.00.
REPORTED = 100


@pytest.mark.parametrize("goal", sorted(RARE_EVENT_GOALS))
def test_a_rare_event_goal_costs_twice_the_reported_floor(goal: str) -> None:
    """100/1885272, "Budget Is Too Low", is what reading the reported
    figure alone produces."""
    assert daily_floor(account_minor=REPORTED, optimization_goal=goal) == (
        REPORTED * RARE_EVENT_MULTIPLIER
    )


@pytest.mark.parametrize(
    "goal",
    [
        pytest.param("REACH", id="reach"),
        pytest.param("LANDING_PAGE_VIEWS", id="traffic"),
        pytest.param("AD_RECALL_LIFT", id="awareness"),
    ],
)
def test_an_impression_goal_takes_the_floor_as_reported(goal: str) -> None:
    assert daily_floor(account_minor=REPORTED, optimization_goal=goal) == REPORTED


def test_the_goal_is_matched_however_it_is_written() -> None:
    """It arrives from a YAML file somebody edits by hand."""
    floor = daily_floor(account_minor=REPORTED, optimization_goal=" quality_call ")

    assert floor == 200


def test_an_unknown_goal_is_not_doubled() -> None:
    """Meta adds optimisation goals between versions. Guessing high blocks
    a real campaign; guessing low is refused by the provider, which is the
    failure that corrects itself."""
    assert daily_floor(account_minor=REPORTED, optimization_goal="SOMETHING_NEW") == 100


def test_no_reported_floor_switches_the_check_off() -> None:
    """Zero means the provider has not told us. Doubling nothing is still
    nothing, and inventing a minimum blocks campaigns that would run."""
    assert daily_floor(account_minor=0, optimization_goal="LEAD_GENERATION") == 0


def test_an_empty_goal_is_not_doubled() -> None:
    """The budget screen runs before anything is built, so the goal can
    genuinely be unknown at the moment the number is typed."""
    assert daily_floor(account_minor=REPORTED, optimization_goal="") == REPORTED


def test_every_goal_the_catalogue_uses_has_a_decided_answer() -> None:
    """Not that they are all doubled - that none of them was overlooked.
    A goal absent from both lists is one nobody decided about."""
    impression_goals = {"REACH", "LANDING_PAGE_VIEWS", "AD_RECALL_LIFT"}
    catalogue = {
        "CONVERSATIONS",
        "QUALITY_CALL",
        "LEAD_GENERATION",
        "LANDING_PAGE_VIEWS",
        "REACH",
        "OFFSITE_CONVERSIONS",
        "AD_RECALL_LIFT",
    }

    assert catalogue <= RARE_EVENT_GOALS | impression_goals


def test_the_floor_takes_no_currency_and_needs_none() -> None:
    """The doubling is arithmetic on a figure the provider already
    denominated.

    ``min_daily_budget`` arrives as an integer count of the ad account
    currency's smallest unit, and multiplying it by two leaves it in the
    same unit. A currency argument here would be a currency this function
    could get wrong for no gain - the same input is the same output on a
    som account and on a dollar one, because the input already means
    something different on each.
    """
    assert daily_floor(account_minor=100, optimization_goal="LEAD_GENERATION") == 200
    assert (
        daily_floor(account_minor=500_000, optimization_goal="LEAD_GENERATION")
        == 1_000_000
    )
    assert "currency" not in inspect.signature(daily_floor).parameters
