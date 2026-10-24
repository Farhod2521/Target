"""Replacing an advert's words or picture, and when learning stops it.

Learning refuses a swap, because a new creative restarts the group's
learning. An advert the provider has stopped is the exception: it delivers
nothing, so there is nothing of its own to protect, and the replacement is
the fix for the fault.
"""

from core.agent import AdContext, ObjectState, check_creative_swap
from core.agent.guardrails import REFUSED_FINISHED, REFUSED_LEARNING

LEARNING = AdContext(parent_is_learning=True, other_active_ads=1)
SETTLED = AdContext(parent_is_learning=False, other_active_ads=1)


def test_a_running_advert_may_be_replaced_once_the_group_has_learned() -> None:
    verdict = check_creative_swap(state=ObjectState(delivery="active"), parent=SETTLED)

    assert verdict.allowed


def test_a_running_advert_in_a_learning_group_is_refused() -> None:
    verdict = check_creative_swap(state=ObjectState(delivery="active"), parent=LEARNING)

    assert not verdict.allowed
    assert verdict.reason == REFUSED_LEARNING


def test_an_advert_the_provider_stopped_is_replaced_even_while_learning() -> None:
    """ "Image Not Found" on a new campaign: waiting keeps the fault running."""
    verdict = check_creative_swap(
        state=ObjectState(delivery="rejected"), parent=LEARNING
    )

    assert verdict.allowed


def test_a_finished_advert_is_refused_whatever_the_group_is_doing() -> None:
    verdict = check_creative_swap(
        state=ObjectState(delivery="finished"), parent=SETTLED
    )

    assert not verdict.allowed
    assert verdict.reason == REFUSED_FINISHED
