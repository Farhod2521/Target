"""core/strategy/maturity: how far along one account is.

No database and no clock. History arrives as a value, and every boundary
is argued with here rather than observed on a customer's account.
"""

from core.strategy import (
    MaturityThresholds,
    SignalHistory,
    has_exited_learning,
    maturity,
)


def _history(**overrides: object) -> SignalHistory:
    figures: dict[str, object] = {
        "window_days": 90,
        "reported_results": 0,
        "days_with_spend": 30,
        "has_proven_adset": False,
    }
    figures.update(overrides)
    return SignalHistory(**figures)  # type: ignore[arg-type]


# --- the provider's own verdict ------------------------------------------
def test_success_is_the_only_word_that_counts() -> None:
    assert has_exited_learning("SUCCESS")
    assert has_exited_learning("  success  ")
    assert not has_exited_learning("LEARNING")
    assert not has_exited_learning("FAIL")
    assert not has_exited_learning("")
    assert not has_exited_learning("WAIVING")


def test_a_proven_adset_makes_the_account_proven() -> None:
    """The verdict is read instead of the bar being guessed: SUCCESS is the
    provider itself saying this account produced enough signal."""
    assert maturity(history=_history(has_proven_adset=True)) == "proven"


def test_the_verdict_does_not_survive_dormancy() -> None:
    """A SUCCESS earned last year on an account that spends nothing now is
    a fact about the past; the arithmetic gets the last word."""
    dormant = _history(has_proven_adset=True, days_with_spend=0)

    assert maturity(history=dormant) == "new"


# --- the arithmetic, when no verdict is available -------------------------
def test_fifty_results_a_week_counts_as_proven() -> None:
    week = _history(window_days=7, reported_results=50, days_with_spend=7)

    assert maturity(history=week) == "proven"


def test_just_under_the_weekly_bar_is_growing() -> None:
    week = _history(window_days=7, reported_results=49, days_with_spend=7)

    assert maturity(history=week) == "growing"


def test_a_trickle_of_results_is_growing_not_new() -> None:
    trickle = _history(reported_results=40)

    assert maturity(history=trickle) == "growing"


def test_below_the_minimum_is_new() -> None:
    thin = _history(reported_results=9)

    assert maturity(history=thin) == "new"


# --- the safe direction ---------------------------------------------------
def test_everything_unknown_lands_on_new() -> None:
    """An empty window, a dormant account - all of it gets the gentlest
    strategy rather than the boldest."""
    assert maturity(history=_history(window_days=0)) == "new"
    assert maturity(history=_history(days_with_spend=0)) == "new"


def test_thresholds_are_the_callers_to_move() -> None:
    lenient = MaturityThresholds(proven_weekly_results=5, min_results=1)
    week = _history(window_days=7, reported_results=5, days_with_spend=7)

    assert maturity(history=week, thresholds=lenient) == "proven"
    assert maturity(history=week) == "new"
