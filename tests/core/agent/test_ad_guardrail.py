"""Switching off one advert is not a small version of stopping a group.

The whole file is one argument. ``check_status_change`` never refuses a
stop, because stopping is how somebody protects themselves from a decision
this product made and it has to work at any moment. That reasoning is about
the owner's ability to **stop their own spending** - and an advert-level
stop does not do that: the group keeps its budget and spends it on whatever
adverts are left. So this is an optimisation, and it answers to the rules
optimisations answer to.
"""

from core.agent import AdContext, ObjectState, check_ad_pause, check_status_change
from core.agent.guardrails import (
    REFUSED_ALREADY,
    REFUSED_FINISHED,
    REFUSED_LAST_AD,
    REFUSED_LEARNING,
)

RUNNING = ObjectState(delivery="active")
WITH_SIBLINGS = AdContext(other_active_ads=2)


def test_an_advert_beside_others_may_be_switched_off() -> None:
    assert check_ad_pause(state=RUNNING, parent=WITH_SIBLINGS).allowed


def test_the_last_running_advert_is_refused() -> None:
    """It would stop the group, silently. Somebody agreed to switch off the
    advert that is not working, not to stop their campaign."""
    verdict = check_ad_pause(state=RUNNING, parent=AdContext(other_active_ads=0))

    assert not verdict.allowed
    assert verdict.reason == REFUSED_LAST_AD


def test_a_learning_group_refuses_a_change_to_its_adverts() -> None:
    """Openly a precaution. Learning belongs to the group and has no
    advert-level equivalent, the provider's reference does not say whether
    removing an advert from the mix restarts it, and being wrong costs days
    of somebody's budget where waiting costs two days."""
    verdict = check_ad_pause(
        state=RUNNING, parent=AdContext(parent_is_learning=True, other_active_ads=2)
    )

    assert not verdict.allowed
    assert verdict.reason == REFUSED_LEARNING


def test_learning_is_answered_before_the_sibling_count() -> None:
    """Both are true here and only one sentence can be shown. The learning
    one is the one worth reading: it says come back in two days, where the
    other says go and use a different button."""
    verdict = check_ad_pause(
        state=RUNNING, parent=AdContext(parent_is_learning=True, other_active_ads=0)
    )

    assert verdict.reason == REFUSED_LEARNING


def test_an_advert_already_off_is_refused_like_anything_else() -> None:
    """The ordinary checks still run underneath: this adds two refusals, it
    does not replace the ones every object has."""
    verdict = check_ad_pause(state=ObjectState(delivery="paused"), parent=WITH_SIBLINGS)

    assert verdict.reason == REFUSED_ALREADY


def test_a_finished_advert_is_refused() -> None:
    verdict = check_ad_pause(
        state=ObjectState(delivery="finished"), parent=WITH_SIBLINGS
    )

    assert verdict.reason == REFUSED_FINISHED


def test_the_group_level_rule_is_untouched() -> None:
    """The load-bearing half of the argument, stated as a test: a stop at a
    level where a stop actually stops the spending is still never refused
    for learning."""
    learning = ObjectState(delivery="active", is_learning=True)

    assert check_status_change(state=learning, wanted="paused").allowed


def test_switching_an_advert_back_on_is_not_this_check_s_business() -> None:
    """The undo has to work. "We turned your advert off and will not turn it
    back on yet" is the one answer a product that proposes changes must
    never give - so a resume goes through the ordinary check, which does
    not consult learning."""
    off = ObjectState(delivery="paused")

    assert check_status_change(state=off, wanted="active").allowed
