"""The rule that chooses the kind of campaign when the owner has not."""

from core.advice import CAMPAIGN_TYPE_REASONS, PROVEN_DEFAULT, campaign_type_advice
from core.targeting import types_for


def test_the_first_proven_kind_is_chosen_with_the_goals_reason() -> None:
    kinds = tuple(row.key for row in types_for(provider="meta", goal="calls"))

    advice = campaign_type_advice(goal="calls", kinds=kinds)

    assert advice is not None
    assert (advice.value, advice.reason) == ("calls_many", "calls_cheapest")


def test_every_goal_with_kinds_has_a_reason_of_its_own() -> None:
    goals = {"calls", "leads", "traffic", "site_leads", "views", "messages"}

    assert goals <= set(CAMPAIGN_TYPE_REASONS)


def test_a_goal_nobody_wrote_a_sentence_for_still_gets_one() -> None:
    advice = campaign_type_advice(goal="somewhere_new", kinds=("a_kind",))

    assert advice is not None
    assert advice.reason == PROVEN_DEFAULT


def test_nothing_to_choose_between_is_no_advice() -> None:
    assert campaign_type_advice(goal="sales", kinds=()) is None
