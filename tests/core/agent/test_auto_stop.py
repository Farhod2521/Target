"""The one stop the agent makes without asking: past half the day, nothing back."""

from core.agent.auto_stop import Fruitless, SmallBudget, must_stop

SMALL = SmallBudget(budget_minor=1_000, spend_minor=500)


def _group(*, spend: int, results: int = 0, budget: int = 2_000) -> Fruitless:
    return Fruitless(
        adset_id="g1", spend_minor=spend, results=results, budget_minor=budget
    )


def test_more_than_half_the_day_gone_for_nothing_is_stopped() -> None:
    assert must_stop(_group(spend=1_001), small=SMALL)


def test_exactly_half_is_not_yet() -> None:
    assert not must_stop(_group(spend=1_000), small=SMALL)


def test_one_result_is_enough_to_leave_it_alone() -> None:
    assert not must_stop(_group(spend=5_000, results=1), small=SMALL)


def test_a_small_budget_waits_for_its_own_bar_rather_than_half() -> None:
    six_dollars = 600

    assert not must_stop(_group(spend=400, budget=six_dollars), small=SMALL)
    assert must_stop(_group(spend=501, budget=six_dollars), small=SMALL)


def test_without_a_small_bar_for_the_currency_half_the_day_decides() -> None:
    assert must_stop(_group(spend=301, budget=600), small=None)


def test_a_group_with_no_day_budget_is_never_stopped_by_this() -> None:
    assert not must_stop(_group(spend=9_000, budget=0), small=SMALL)
