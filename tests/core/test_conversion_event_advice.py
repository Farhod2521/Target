"""Which event on a website a campaign should be bought against.

One fact decides it - has the tag been seen sending this - and the rule
exists because the wrong answer is invisible: an ad set bought against an
event nobody sends delivers, spends, and reports nothing.
"""

from core.advice import (
    EVENT_ALREADY_ARRIVING,
    EVENT_NOTHING_SEEN,
    conversion_event_advice,
)
from core.targeting import REQUEST_EVENTS

OFFERED = ("LEAD", "CONTACT", "SCHEDULE", "CONTENT_VIEW", "PURCHASE")


def advice(fired: tuple[str, ...]) -> object:
    return conversion_event_advice(
        offered=OFFERED, fired=fired, requests=REQUEST_EVENTS
    )


def test_nothing_seen_falls_back_to_the_catalogues_own_event() -> None:
    found = advice(())

    assert found is not None
    assert (found.value, found.reason) == ("LEAD", EVENT_NOTHING_SEEN)


def test_an_event_the_site_already_sends_is_chosen() -> None:
    found = advice(("CONTACT",))

    assert found is not None
    assert (found.value, found.reason) == ("CONTACT", EVENT_ALREADY_ARRIVING)


def test_a_request_wins_over_a_look_even_when_the_look_is_commoner() -> None:
    """A tag fires a view on every page and a request once a week.

    Buying the frequent one sends the provider after people who look.
    """
    found = advice(("CONTENT_VIEW", "SCHEDULE"))

    assert found is not None
    assert found.value == "SCHEDULE"


def test_a_site_that_only_looks_is_bought_on_looking() -> None:
    """Weak, and still better than an event the site has never sent."""
    found = advice(("CONTENT_VIEW",))

    assert found is not None
    assert (found.value, found.reason) == ("CONTENT_VIEW", EVENT_ALREADY_ARRIVING)


def test_an_event_arriving_that_is_not_on_offer_is_ignored() -> None:
    found = advice(("ADD_TO_WISHLIST",))

    assert found is not None
    assert found.reason == EVENT_NOTHING_SEEN


def test_nothing_to_choose_between_is_no_advice() -> None:
    assert (
        conversion_event_advice(offered=(), fired=("LEAD",), requests=REQUEST_EVENTS)
        is None
    )
