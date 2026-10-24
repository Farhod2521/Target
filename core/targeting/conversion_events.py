"""Which thing on the advertiser's own site counts as the result."""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ConversionEvent:
    """One event a tag on the advertiser's site can report."""

    provider: str
    key: str
    provider_label: str


CONVERSION_EVENTS: Final[tuple[ConversionEvent, ...]] = (
    ConversionEvent("meta", "LEAD", "Lead"),
    ConversionEvent("meta", "CONTACT", "Contact"),
    ConversionEvent("meta", "COMPLETE_REGISTRATION", "Complete registration"),
    ConversionEvent("meta", "SUBMIT_APPLICATION", "Submit application"),
    ConversionEvent("meta", "SCHEDULE", "Schedule"),
    ConversionEvent("meta", "START_TRIAL", "Start trial"),
    ConversionEvent("meta", "SUBSCRIBE", "Subscribe"),
    ConversionEvent("meta", "FIND_LOCATION", "Find location"),
    ConversionEvent("meta", "CONTENT_VIEW", "View content"),
    ConversionEvent("meta", "SEARCH", "Search"),
    ConversionEvent("meta", "ADD_TO_CART", "Add to cart"),
    ConversionEvent("meta", "ADD_TO_WISHLIST", "Add to wishlist"),
    ConversionEvent("meta", "INITIATED_CHECKOUT", "Initiate checkout"),
    ConversionEvent("meta", "ADD_PAYMENT_INFO", "Add payment info"),
    ConversionEvent("meta", "PURCHASE", "Purchase"),
    ConversionEvent("meta", "DONATE", "Donate"),
    ConversionEvent("meta", "OTHER", "Other"),
)

EVENT_KEY: Final = "custom_event_type"
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
    """The event a tag's own name for it may be bought against, if any."""
    key = SNIPPET_EVENTS.get(name.strip())
    return None if key is None else conversion_event(provider=provider, key=key)


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
    """The named event, or ``None`` for one this provider has no word for."""
    return _BY_KEY.get((provider, key))


def counts_a_request(event: ConversionEvent) -> bool:
    """Whether this event means somebody asked, rather than looked or bought."""
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
