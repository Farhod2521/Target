"""The one stop the agent makes without asking: past half the day, nothing back."""

from core.agent.auto_stop import Fruitless, SmallBudget, must_stop

SMALL = SmallBudget(budget_minor=1_000, spend_minor=500)


def _group(
    *,
    spend: int,
    results: int = 0,
    budget: int = 2_000,
    impressions: int = 2_000,
    link_clicks: int = 40,
    usual: int | None = None,
) -> Fruitless:
    """A group shown enough to judge, unless a test says otherwise."""
    return Fruitless(
        adset_id="g1",
        spend_minor=spend,
        results=results,
        budget_minor=budget,
        impressions=impressions,
        link_clicks=link_clicks,
        usual_cost_minor=usual,
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


# --- only once there is enough to judge by ----------------------------------
def test_a_group_shown_too_little_is_not_stopped_however_much_went() -> None:
    """Past half the day, but shown a few hundred times: it has said nothing
    yet, and stopping it would be judging it on noise."""
    assert not must_stop(
        _group(spend=1_500, impressions=400, link_clicks=5), small=SMALL
    )


def test_too_few_clicks_is_not_enough_either() -> None:
    assert not must_stop(
        _group(spend=1_500, impressions=5_000, link_clicks=10), small=SMALL
    )


def test_three_usual_results_spent_is_enough_without_the_clicks() -> None:
    assert must_stop(
        _group(spend=1_500, impressions=400, link_clicks=5, usual=500), small=SMALL
    )


def test_with_a_usual_price_only_three_results_worth_is_enough() -> None:
    """The brief's rule: where a result has a usual price, the showings do not
    stand in for it - under three of them spent, nothing is decided."""
    assert not must_stop(
        _group(spend=1_400, impressions=5_000, link_clicks=80, usual=500), small=SMALL
    )
