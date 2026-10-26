"""A group past its first week: stopped, dry, dearer, cheaper - said once each."""

from dataclasses import replace
from datetime import date

from core.agent.launch_watch import WatchedGroup, moved_budget
from core.agent.running_watch import Running, Tally, running_watch

BUDGET = 100_000
USUAL = 20_000


def _group(**overrides: object) -> WatchedGroup:
    fields: dict[str, object] = {
        "adset_id": "1",
        "hours": 10 * 24.0,
        "spend_minor": 0,
        "results": 0,
        "daily_budget_minor": BUDGET,
    }
    fields.update(overrides)
    return WatchedGroup(**fields)  # type: ignore[arg-type]


QUIET = Running(
    dry_days=0,
    dry_spend_minor=0,
    spell=40,
    expected_cost_minor=USUAL,
    recent=Tally(spend_minor=7 * BUDGET, results=35),
    before=Tally(spend_minor=21 * BUDGET, results=105),
    idle_days=0,
    idle_since=None,
    spent_before=True,
    week="2026-W41",
)


def _facts(**overrides: object) -> Running:
    return replace(QUIET, **overrides)  # type: ignore[arg-type]


def test_a_group_doing_what_it_did_says_nothing() -> None:
    assert running_watch(_group(), QUIET) is None


# --- Stopped -----------------------------------------------------------------


def test_a_day_with_nothing_spent_after_spending_is_said() -> None:
    found = running_watch(_group(), _facts(idle_days=1, idle_since=date(2026, 10, 13)))
    assert found is not None
    assert found.stage == "stalled"
    # Days with nothing spent are nothing to judge by: no budget button.
    assert (found.moves, found.advised) == (("wait",), "wait")
    assert found.tag == "2026-10-13"


def test_spending_again_today_takes_it_back() -> None:
    facts = _facts(idle_days=2, idle_since=date(2026, 10, 12))
    assert running_watch(_group(spend_minor=500), facts) is None


def test_a_week_with_nothing_spent_is_a_pause_not_a_stall() -> None:
    """Somebody switched it off and on again; the days it was off are old."""
    facts = _facts(idle_days=5, idle_since=date(2026, 10, 9))
    assert running_watch(_group(), facts) is None


def test_a_limited_group_s_price_is_not_judged() -> None:
    facts = _facts(recent=Tally(spend_minor=7 * BUDGET, results=60))
    assert running_watch(_group(limited=True), facts) is None


def test_a_group_that_never_spent_is_not_stopped() -> None:
    facts = _facts(idle_days=9, spent_before=False)
    assert running_watch(_group(), facts) is None


def test_a_shared_budget_is_not_offered_from_one_group() -> None:
    found = running_watch(_group(owns_budget=False), _facts(idle_days=1))
    assert found is not None
    assert found.moves == ("wait",)


# --- Nothing back ------------------------------------------------------------


def test_three_dry_days_worth_a_result_are_said_and_waited() -> None:
    found = running_watch(_group(), _facts(dry_days=3, dry_spend_minor=USUAL))
    assert found is not None
    assert (found.stage, found.advised) == ("dry", "wait")
    # The spell is named by the results so far, which hold still while it
    # lasts - however far its start slides back.
    assert found.tag == "3:40"


def test_three_dry_days_worth_three_results_are_advised_paused() -> None:
    found = running_watch(_group(), _facts(dry_days=3, dry_spend_minor=3 * USUAL))
    assert found is not None
    assert found.advised == "pause"


def test_a_long_spell_is_paused_only_on_three_results_worth() -> None:
    """The brief decides nothing under three results' usual price, however
    many days the spell has run."""
    found = running_watch(_group(), _facts(dry_days=9, dry_spend_minor=USUAL))
    assert found is not None
    assert (found.advised, found.tag) == ("wait", "7:40")


def test_dry_days_too_cheap_to_have_bought_one_say_nothing() -> None:
    facts = _facts(dry_days=5, dry_spend_minor=USUAL - 1)
    assert running_watch(_group(), facts) is None


def test_without_any_price_the_budget_is_the_bar() -> None:
    facts = _facts(dry_days=3, expected_cost_minor=None)
    assert running_watch(_group(), replace(facts, dry_spend_minor=BUDGET)) is None
    found = running_watch(_group(), replace(facts, dry_spend_minor=BUDGET * 3 // 2))
    assert found is not None
    assert found.stage == "dry"


def test_a_result_today_ends_the_dry_spell() -> None:
    facts = _facts(dry_days=7, dry_spend_minor=5 * USUAL)
    assert running_watch(_group(results=1), facts) is None


def test_a_learning_group_three_days_dry_is_waited_for() -> None:
    facts = _facts(dry_days=3, dry_spend_minor=5 * USUAL)
    found = running_watch(_group(learning=True), facts)
    assert found is not None
    assert found.advised == "wait"


# --- Price -------------------------------------------------------------------


def _dear(spend: int, results: int) -> Running:
    """The last three days at this price, against a fortnight's ``USUAL``."""
    return _facts(
        last=Tally(spend_minor=spend, results=results), usual_cost_minor=USUAL
    )


def test_past_twice_the_usual_on_a_shared_budget_is_advised_paused() -> None:
    found = running_watch(_group(owns_budget=False), _dear(5 * USUAL, 2))
    assert found is not None
    assert found.stage == "dearer"
    assert (found.moves, found.advised, found.tag) == (
        ("pause", "wait"),
        "pause",
        "2026-W41",
    )


def test_a_budget_of_its_own_is_left_to_the_nights_card() -> None:
    """The night's budget card reads the same price; a message beside it
    would say it twice."""
    assert running_watch(_group(), _dear(5 * USUAL, 2)) is None


def test_under_twice_the_usual_is_the_reports_not_a_message() -> None:
    assert running_watch(_group(owns_budget=False), _dear(4 * USUAL, 2)) is None


def test_under_three_results_worth_spent_nothing_is_said() -> None:
    facts = replace(
        _dear(3 * USUAL - 1, 1), recent=Tally(spend_minor=3 * USUAL - 1, results=1)
    )
    assert running_watch(_group(owns_budget=False), facts) is None


def test_a_small_budget_s_dear_days_are_judged_on_the_whole_week() -> None:
    """Three days under three results' worth, a week past it: the brief asks
    whether the group has said enough, not whether three days have."""
    found = running_watch(_group(owns_budget=False), _dear(2 * USUAL + USUAL // 2, 1))
    assert found is not None
    assert found.stage == "dearer"


def test_without_a_fortnights_median_the_price_is_not_judged() -> None:
    facts = replace(_dear(5 * USUAL, 2), usual_cost_minor=None)
    assert running_watch(_group(owns_budget=False), facts) is None


def test_a_price_needs_the_weeks_before_to_have_been_a_price() -> None:
    facts = _facts(
        recent=Tally(spend_minor=7 * BUDGET, results=5),
        before=Tally(spend_minor=BUDGET, results=4),
    )
    assert running_watch(_group(), facts) is None


def test_a_learning_group_s_price_is_not_judged() -> None:
    facts = _facts(recent=Tally(spend_minor=7 * BUDGET, results=10))
    assert running_watch(_group(learning=True), facts) is None


def test_cheaper_with_the_budget_spent_up_is_offered_more() -> None:
    facts = _facts(
        recent=Tally(spend_minor=7 * BUDGET, results=60), usual_cost_minor=USUAL
    )
    found = running_watch(_group(), facts)
    assert found is not None
    assert (found.stage, found.moves) == ("cheaper", ("budget_up", "wait"))


def test_cheaper_under_three_results_worth_is_not_offered_more() -> None:
    """A budget change, and the brief makes none before there is enough."""
    facts = _facts(
        recent=Tally(spend_minor=7 * BUDGET, results=60),
        usual_cost_minor=7 * BUDGET // 3 + 1,
    )
    assert running_watch(_group(), facts) is None


def test_cheaper_with_budget_left_over_says_nothing() -> None:
    facts = _facts(recent=Tally(spend_minor=5 * BUDGET, results=60))
    assert running_watch(_group(), facts) is None


def test_the_running_step_is_a_fifth() -> None:
    assert moved_budget(budget_minor=BUDGET, move="budget_up", step_pct=20) == 120_000
