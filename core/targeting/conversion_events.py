"""Which thing on the advertiser's own site counts as the result.

A goal whose result happens off the provider's property is bought against
an event a tag on that site reports - and which event is not a detail. The
provider optimises towards the one it is told, so an ad set naming an event
the site never sends is bought against nothing: it delivers, it spends, and
the count it was sold on stays at zero while every screen looks ordinary.

**The provider demands the pairing, not the event.** A dataset named with
no event beside it is refused outright, so the preset carries a default and
this table is what may replace it. Nothing here is guessed from the site:
what a shop calls a request is the shop's own business, and the only honest
source is the person who set the tag up - or the events that tag has
actually been seen sending.

The provider's own vocabulary, like the presets and the campaign kinds
beside it: these words are what gets sent. What the owner reads is decided
above this package.

Ordered as a person answers, not as the provider lists: the events that
mean *somebody asked us for something* first, then the ones that mean
*somebody bought something*. A shop that wants the second is choosing it
deliberately and will scroll; a clinic looking for the first should not
have to.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ConversionEvent:
    """One event a tag on the advertiser's site can report."""

    provider: str
    # The provider's own value, sent as it is written here.
    key: str
    # What the provider's own screen calls it. Shown beside the owner's
    # words where the event is chosen - never the API's spelling.
    provider_label: str


CONVERSION_EVENTS: Final[tuple[ConversionEvent, ...]] = (
    # Somebody asked for something. The first is the default every preset
    # that needs an event carries, and the commonest tag setup sends it.
    ConversionEvent("meta", "LEAD", "Lead"),
    ConversionEvent("meta", "CONTACT", "Contact"),
    ConversionEvent("meta", "COMPLETE_REGISTRATION", "Complete registration"),
    ConversionEvent("meta", "SUBMIT_APPLICATION", "Submit application"),
    ConversionEvent("meta", "SCHEDULE", "Schedule"),
    ConversionEvent("meta", "START_TRIAL", "Start trial"),
    ConversionEvent("meta", "SUBSCRIBE", "Subscribe"),
    ConversionEvent("meta", "FIND_LOCATION", "Find location"),
    # Somebody looked at something. Weak as a result on its own - a page
    # view is not a customer - and offered because a site that reports
    # nothing else is better bought against this than against an event it
    # never sends.
    ConversionEvent("meta", "CONTENT_VIEW", "View content"),
    ConversionEvent("meta", "SEARCH", "Search"),
    # Somebody bought something, or started to.
    ConversionEvent("meta", "ADD_TO_CART", "Add to cart"),
    ConversionEvent("meta", "ADD_TO_WISHLIST", "Add to wishlist"),
    ConversionEvent("meta", "INITIATED_CHECKOUT", "Initiate checkout"),
    ConversionEvent("meta", "ADD_PAYMENT_INFO", "Add payment info"),
    ConversionEvent("meta", "PURCHASE", "Purchase"),
    ConversionEvent("meta", "DONATE", "Donate"),
    # The provider's own catch-all, for a tag sending something with no
    # standard name at all.
    ConversionEvent("meta", "OTHER", "Other"),
)

# What the provider calls the field the event goes in, beside the dataset
# id. Named here rather than spelled at the two call sites, because the
# provider refuses the pair when either half is missing and a misspelling
# is exactly the failure that produces.
EVENT_KEY: Final = "custom_event_type"
# The events that mean somebody asked to be contacted. A set rather than a
# slice of the tuple above, so re-ordering the list for how it reads cannot
# quietly change what a rule considers a request.
REQUEST_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "LEAD",
        "CONTACT",
        "COMPLETE_REGISTRATION",
        "SUBMIT_APPLICATION",
        "SCHEDULE",
        "START_TRIAL",
        "SUBSCRIBE",
        "FIND_LOCATION",
    }
)

_BY_KEY: Final[dict[tuple[str, str], ConversionEvent]] = {
    (row.provider, row.key): row for row in CONVERSION_EVENTS
}

_BY_PROVIDER: Final[dict[str, tuple[ConversionEvent, ...]]] = {}
for _row in CONVERSION_EVENTS:
    _BY_PROVIDER[_row.provider] = (*_BY_PROVIDER.get(_row.provider, ()), _row)


# The provider says the same event two ways and this is the table between
# them. A tag on a website fires an event under the name its own snippet
# uses - ``ViewContent``, ``CompleteRegistration`` - while an ad set names
# the same thing as an enum - ``CONTENT_VIEW``, ``COMPLETE_REGISTRATION``.
# Reading what a tag has been sending and offering it as something to buy
# against means crossing between the two, and the crossing is not a
# transliteration: three of the pairs below disagree about more than case.
#
# Here rather than in the package that reads the tag's own figures, because
# both halves are the same vocabulary and splitting them is what lets one
# half drift. A name missing from this table is an event nothing can be
# bought against - the provider's own ``PageView`` is the commonest.
SNIPPET_EVENTS: Final[dict[str, str]] = {
    "Lead": "LEAD",
    "Contact": "CONTACT",
    "CompleteRegistration": "COMPLETE_REGISTRATION",
    "SubmitApplication": "SUBMIT_APPLICATION",
    "Schedule": "SCHEDULE",
    "StartTrial": "START_TRIAL",
    "Subscribe": "SUBSCRIBE",
    "FindLocation": "FIND_LOCATION",
    "ViewContent": "CONTENT_VIEW",
    "Search": "SEARCH",
    "AddToCart": "ADD_TO_CART",
    "AddToWishlist": "ADD_TO_WISHLIST",
    "InitiateCheckout": "INITIATED_CHECKOUT",
    "AddPaymentInfo": "ADD_PAYMENT_INFO",
    "Purchase": "PURCHASE",
    "Donate": "DONATE",
}


def event_for_snippet(*, provider: str, name: str) -> ConversionEvent | None:
    """The event a tag's own name for it may be bought against, if any.

    ``None`` for a name with no ad-set spelling - an ordinary page view, or
    something the advertiser invented - which is not a failure: those are
    real events a tag sends and simply not things to optimise towards.
    """
    key = SNIPPET_EVENTS.get(name.strip())
    return None if key is None else conversion_event(provider=provider, key=key)


# Which events each objective takes. Meta refuses a pairing across the line
# - a purchase bought under the leads objective, a lead under sales - so a
# list that offers every event under every objective offers a launch that
# fails at the ad set. An objective missing here takes the whole list.
_OBJECTIVE_EVENTS: Final[dict[str, frozenset[str]]] = {
    "OUTCOME_LEADS": REQUEST_EVENTS,
    "OUTCOME_SALES": frozenset(
        row.key for row in CONVERSION_EVENTS if row.key not in REQUEST_EVENTS
    ),
}


def events_for(*, provider: str, objective: str) -> tuple[ConversionEvent, ...]:
    """Every event this objective may be bought against, in reading order."""
    allowed = _OBJECTIVE_EVENTS.get(objective)
    return tuple(
        row
        for row in conversion_events(provider=provider)
        if allowed is None or row.key in allowed
    )


def conversion_events(*, provider: str) -> tuple[ConversionEvent, ...]:
    """Every event this provider counts, in the order somebody reads them."""
    return _BY_PROVIDER.get(provider, ())


def conversion_event(*, provider: str, key: str) -> ConversionEvent | None:
    """The named event, or ``None`` for one this provider has no word for.

    ``None`` rather than a fallback, which is the opposite of how a
    campaign kind resolves and deliberately so: an unknown kind still
    builds the goal's default campaign, while an unknown event would build
    an ad set optimising towards something nobody named. The caller keeps
    the preset's own event instead.
    """
    return _BY_KEY.get((provider, key))


def counts_a_request(event: ConversionEvent) -> bool:
    """Whether this event means somebody asked, rather than looked or bought.

    What a rule reads when it has to pick one and the site reports several:
    a tag sending both a request and a page view is sending one event the
    campaign was bought for and one it was not.
    """
    return event.key in REQUEST_EVENTS


__all__ = [
    "CONVERSION_EVENTS",
    "EVENT_KEY",
    "REQUEST_EVENTS",
    "SNIPPET_EVENTS",
    "ConversionEvent",
    "conversion_event",
    "conversion_events",
    "counts_a_request",
    "event_for_snippet",
    "events_for",
]
