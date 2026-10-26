"""The one question a day that is not over can answer."""

from core.agent.same_day import TodayGroup, burning


def a_day(**overrides: object) -> TodayGroup:
    values: dict[str, object] = {
        "adset_id": "1",
        "spend_minor": 384,
        "impressions": 9_289,
        "results": 0,
        "daily_budget_minor": 1_500,
    }
    values.update(overrides)
    return TodayGroup(**values)  # type: ignore[arg-type]


def test_a_quarter_of_the_budget_shown_to_thousands_for_nothing_is_said() -> None:
    """The morning this exists for: $3.84 of $15, nine thousand showings,
    nobody at the site."""
    assert burning(a_day())


def test_one_result_is_enough_to_stay_quiet() -> None:
    assert not burning(a_day(results=1))


def test_a_group_barely_shown_is_left_alone() -> None:
    assert not burning(a_day(impressions=1_999))


def test_less_than_a_quarter_of_the_budget_is_left_alone() -> None:
    assert not burning(a_day(spend_minor=374))


def test_without_a_budget_three_usual_results_are_the_bar() -> None:
    assert burning(
        a_day(daily_budget_minor=None, usual_cost_minor=120, spend_minor=360)
    )
    assert not burning(
        a_day(daily_budget_minor=None, usual_cost_minor=120, spend_minor=359)
    )


def test_with_nothing_to_measure_against_nothing_is_said() -> None:
    assert not burning(a_day(daily_budget_minor=None, usual_cost_minor=None))


def test_under_three_usual_results_spent_nothing_is_decided() -> None:
    """The brief's rule: a quarter of the budget gone, but less than three
    results' usual price - not enough to call it money for nothing."""
    assert not burning(a_day(usual_cost_minor=200))
    assert burning(a_day(usual_cost_minor=128))


def test_with_no_usual_price_the_showings_stand_in() -> None:
    """Shown nine thousand times and tapped by nobody: no price says what
    three results cost, and a bar on clicks would never reach this group."""
    assert burning(a_day(usual_cost_minor=None))
