"""The two ways a new group goes quiet, and the hour each is said."""

import pytest

from core.agent.launch_watch import WatchedGroup, moved_budget, watch

BUDGET = 100_000


def _group(**overrides: object) -> WatchedGroup:
    fields: dict[str, object] = {
        "adset_id": "1",
        "hours": 6.0,
        "spend_minor": 0,
        "results": 0,
        "daily_budget_minor": BUDGET,
    }
    fields.update(overrides)
    return WatchedGroup(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("hours", [0, 5.9])
def test_says_nothing_in_the_first_hours(hours: float) -> None:
    assert watch(_group(hours=hours)) is None


def test_says_nothing_once_the_group_is_a_week_old() -> None:
    assert watch(_group(hours=7 * 24)) is None


def test_unstarted_at_six_hours_is_waited_for() -> None:
    found = watch(_group(hours=6))
    assert found is not None
    assert (found.stage, found.moves, found.advised) == ("unstarted", ("wait",), "wait")


def test_unstarted_at_a_day_under_review_is_still_waited_for() -> None:
    found = watch(_group(hours=24, in_review=True))
    assert found is not None
    assert (found.stage, found.advised) == ("in_review", "wait")


def test_approved_and_idle_at_a_day_is_offered_the_budget() -> None:
    found = watch(_group(hours=24))
    assert found is not None
    assert found.stage == "idle"
    assert found.moves == ("budget_up", "budget_down", "wait")
    assert found.advised == "budget_up"


def test_a_shared_budget_is_not_offered_from_one_group() -> None:
    found = watch(_group(hours=24, owns_budget=False))
    assert found is not None
    assert (found.stage, found.moves) == ("idle", ("wait",))


def test_unstarted_at_two_days_is_advised_deleted() -> None:
    found = watch(_group(hours=48, in_review=True))
    assert found is not None
    assert (found.stage, found.advised) == ("stuck", "delete")


def test_a_blocked_group_is_left_to_the_line_naming_its_cause() -> None:
    assert watch(_group(hours=48, blocked=True)) is None


def test_half_a_budget_for_nothing_at_a_day_is_a_word_not_a_change() -> None:
    found = watch(_group(hours=24, spend_minor=BUDGET // 2))
    assert found is not None
    assert (found.stage, found.moves) == ("quiet", ("wait",))


def test_less_than_half_a_budget_says_nothing() -> None:
    assert watch(_group(hours=30, spend_minor=BUDGET // 2 - 1)) is None


def test_spend_before_a_day_says_nothing() -> None:
    assert watch(_group(hours=20, spend_minor=BUDGET)) is None


def test_three_days_for_nothing_is_advised_deleted() -> None:
    found = watch(_group(hours=72, spend_minor=BUDGET * 3 // 2))
    assert found is not None
    assert found.stage == "fruitless"
    assert found.moves == ("delete", "pause", "wait")
    assert found.advised == "delete"


def test_three_days_with_little_spent_stays_a_word() -> None:
    found = watch(_group(hours=80, spend_minor=BUDGET))
    assert found is not None
    assert found.stage == "quiet"


def test_one_result_ends_it() -> None:
    assert watch(_group(hours=72, spend_minor=BUDGET * 3, results=1)) is None


def test_a_group_bought_to_be_seen_has_no_nothing_back() -> None:
    assert watch(_group(hours=72, spend_minor=BUDGET * 3, results=None)) is None


def test_no_daily_budget_has_no_share_to_measure() -> None:
    assert watch(_group(hours=72, spend_minor=BUDGET, daily_budget_minor=None)) is None


def test_budget_moves_by_half_either_way() -> None:
    assert moved_budget(budget_minor=BUDGET, move="budget_up") == 150_000
    assert moved_budget(budget_minor=BUDGET, move="budget_down") == 50_000
    assert moved_budget(budget_minor=1, move="budget_down") == 1
