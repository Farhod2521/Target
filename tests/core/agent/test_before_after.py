"""core/agent/before_after: the figure a verdict rests on, before and after.

No database and no clock. Both sides arrive as the mappings the approval
and the assessment store, which is what lets the edges - a pause's empty
aftermath, a price with no lead behind it, a starting point nobody wrote
down - be argued here.
"""

from core.agent.before_after import before_after
from core.agent.rules import (
    EXPENSIVE,
    IDLE,
    NARROW_AUDIENCE,
    SATURATED,
    WASTING,
    WEAK_AD,
    WINNING,
)

WORN = {"days": 7, "early_ctr_bp": 90, "late_ctr_bp": 40}
READ = {"days": 5, "spend_minor": 50_000, "impressions": 5_000, "link_clicks": 60}


def test_a_pause_is_measured_in_spend_per_day() -> None:
    change = before_after(
        rule=WASTING,
        evidence={"days": 5, "spend_minor": 450_000},
        after={"days": 0, "spend_minor": 0},
    )

    assert change is not None
    assert (change.measure, change.before, change.after) == ("daily_spend", 90_000, 0)


def test_a_resumed_group_goes_from_nothing_to_its_new_daily_spend() -> None:
    change = before_after(
        rule=IDLE,
        evidence={"days": 3, "spend_minor": 0},
        after={"days": 2, "spend_minor": 8_000},
    )

    assert change is not None
    assert (change.before, change.after) == (0, 4_000)


def test_attention_is_measured_on_link_clicks_against_the_worn_half() -> None:
    change = before_after(rule=SATURATED, evidence=WORN, after=READ)

    assert change is not None
    assert (change.measure, change.before, change.after) == ("link_ctr", 40, 120)
    assert (change.days_before, change.days_after) == (7, 5)


def test_a_narrowing_is_priced_on_the_providers_own_lead_count() -> None:
    change = before_after(
        rule=NARROW_AUDIENCE,
        evidence={"days": 7, "spend_minor": 70_000, "leads_reported": 7},
        after={"days": 4, "spend_minor": 40_000, "leads_reported": 8},
    )

    assert change is not None
    assert (change.measure, change.before, change.after) == (
        "cost_per_lead",
        10_000,
        5_000,
    )


def test_no_lead_since_the_change_is_not_a_price_of_nought() -> None:
    change = before_after(
        rule=NARROW_AUDIENCE,
        evidence={"days": 7, "spend_minor": 70_000, "leads_reported": 7},
        after={"days": 4, "spend_minor": 40_000, "leads_reported": 0},
    )

    assert change is not None
    assert (change.before, change.after) == (10_000, None)


def test_an_advert_switched_off_is_priced_on_its_group() -> None:
    change = before_after(
        rule=WEAK_AD,
        evidence={
            "days": 7,
            "spend_minor": 5_000,
            "adset_spend_minor": 70_000,
            "adset_leads_reported": 7,
        },
        after={"days": 4, "spend_minor": 40_000, "leads_reported": 8},
    )

    assert change is not None
    assert (change.before, change.after) == (10_000, 5_000)


def test_a_budget_cut_is_compared_on_its_price_per_lead() -> None:
    """The figure the rule fired on and its check graded, both sides."""
    change = before_after(
        rule=EXPENSIVE,
        evidence={"days": 7, "spend_minor": 105_000, "cpl_minor": 21_000},
        after={"days": 4, "spend_minor": 40_000, "cpl_minor": 13_333},
    )

    assert change is not None
    assert (change.measure, change.before, change.after) == (
        "cost_per_lead",
        21_000,
        13_333,
    )


def test_a_raise_is_not_reduced_to_one_figure() -> None:
    """Graded on more leads *and* a held price; either alone misreports it."""
    assert (
        before_after(
            rule=WINNING,
            evidence={"days": 7, "spend_minor": 70_000, "cpl_minor": 9_000},
            after={"days": 4, "spend_minor": 40_000, "cpl_minor": 8_000},
        )
        is None
    )


def test_a_verdict_with_no_sums_behind_it_has_nothing_to_compare() -> None:
    """A vanished object and a wait that ran out store no sums at all."""
    assert before_after(rule=SATURATED, evidence=WORN, after={}) is None
    assert before_after(rule=SATURATED, evidence=WORN, after={"days": 6}) is None


def test_a_starting_point_nobody_wrote_down_is_not_guessed() -> None:
    assert before_after(rule=SATURATED, evidence={"days": 7}, after=READ) is None
    assert before_after(rule="retired_rule", evidence=WORN, after=READ) is None
