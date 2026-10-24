"""The most a campaign may pay for one result.

The only provider setting in this product that asks a question in the words
the customer already uses - "do not pay more than twenty thousand for one
enquiry" - which is why it is the one bid strategy of Meta's four that was
worth offering at all.

Two rules and both are about the same danger. A cap that is too low relative
to the daily budget does not deliver worse, it delivers **nothing**: the
provider has no room to pace, shows the ad to almost nobody, and reports no
spend, no leads and no cost per lead - which is indistinguishable, on every
screen in this product, from a campaign that has not started yet.
"""

import pytest

from core.targeting.budget import (
    CAP_BUDGET_MULTIPLE,
    accepts_cap,
    cap_fits,
    min_daily_for_cap,
)

CAP = 20_000


# --- Which goals may carry one -------------------------------------------
@pytest.mark.parametrize("goal", ["LEAD_GENERATION", "OFFSITE_CONVERSIONS"])
def test_a_goal_the_provider_takes_a_cap_for_may_be_capped(goal: str) -> None:
    assert accepts_cap(goal)


@pytest.mark.parametrize("goal", ["QUALITY_CALL", "CONVERSATIONS", "QUALITY_LEAD"])
def test_a_call_a_conversation_and_qualified_leads_may_not(goal: str) -> None:
    """Meta refused the first two on creation - 100/1885204 "only supports
    autobid" and 100/2446166 "incompatible with cost cap" - and the third
    has never been seen through."""
    assert not accepts_cap(goal)


@pytest.mark.parametrize(
    "goal", ["REACH", "IMPRESSIONS", "AD_RECALL_LIFT", "LANDING_PAGE_VIEWS"]
)
def test_a_goal_with_no_person_at_the_end_may_not(goal: str) -> None:
    """ "Do not pay more than 20 000 for one impression" is not a sentence
    anybody means, and a visit is counted on the advertiser's own side."""
    assert not accepts_cap(goal)


def test_an_unchosen_goal_takes_no_cap() -> None:
    """A real case rather than a guard: the budget screen renders before the
    goal has been picked, and offering a cap there would ask for a price on
    a result nobody has chosen."""
    assert not accepts_cap("")


# --- Whether the pair can deliver ----------------------------------------
def test_a_budget_several_times_the_cap_delivers() -> None:
    assert cap_fits(cap_minor=CAP, daily_budget_minor=CAP * CAP_BUDGET_MULTIPLE)


def test_a_budget_that_leaves_no_room_to_pace_is_refused() -> None:
    """One result's worth of budget is not a campaign - it is a day spent
    hunting for a single impression at or under a price."""
    assert not cap_fits(cap_minor=CAP, daily_budget_minor=CAP)


def test_the_boundary_is_included() -> None:
    """Exactly the multiple, not merely past it. A strict comparison would
    refuse the number this product's own error message tells somebody to
    type."""
    needed = min_daily_for_cap(cap_minor=CAP)

    assert cap_fits(cap_minor=CAP, daily_budget_minor=needed)


def test_no_cap_always_fits() -> None:
    """Uncapped is what every campaign this product made before the question
    existed, and it has no requirement to meet."""
    assert cap_fits(cap_minor=0, daily_budget_minor=1)


def test_a_negative_cap_is_read_as_no_cap() -> None:
    """Reachable only from a hand-edited row, and the safe reading is the
    behaviour the account already had."""
    assert cap_fits(cap_minor=-5, daily_budget_minor=1)
    assert min_daily_for_cap(cap_minor=-5) == 0
