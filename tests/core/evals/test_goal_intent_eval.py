"""The first step's eval cases and how a reading is marked against them."""

from core.agent import ChoiceReading
from core.evals.goal_intent import GoalCase, load_goal_cases, mark
from core.targeting import OFFERS, OUTCOMES

# What the model is shown - rows no longer offered are not an answer.
ROWS = {row.key for row in OFFERS if row.listed}


def test_the_cases_name_only_rows_the_model_is_shown() -> None:
    cases = load_goal_cases()

    assert len(cases) == 42
    assert len({case.id for case in cases}) == 42
    for case in cases:
        assert not case.expect or case.expect in ROWS, case.id
        assert set(case.accept) <= ROWS and set(case.closed) <= ROWS, case.id


def test_every_live_outcome_is_asked_about() -> None:
    expected = {
        row.outcome
        for case in load_goal_cases()
        for row in OFFERS
        if row.key == case.expect
    }

    assert expected == {spec.key for spec in OUTCOMES if spec.live}


def test_the_marks() -> None:
    case = GoalCase(
        id="x", text="", category="", expect="calls_ready", accept=("calls_engaged",)
    )

    assert mark(case, ChoiceReading("found", "calls_ready"), provider="meta") == "exact"
    assert (
        mark(case, ChoiceReading("found", "calls_engaged"), provider="meta")
        == "accepted"
    )
    assert (
        mark(case, ChoiceReading("found", "calls_many"), provider="meta") == "outcome"
    )
    assert mark(case, ChoiceReading("found", "form_leads"), provider="meta") == "wrong"
    assert mark(case, ChoiceReading("unclear"), provider="meta") == "wrong"
