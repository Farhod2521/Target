"""The button on the advert, and which ones each kind of advert may carry.

The catalogue picks one per goal and it is nearly always right - a clinic
collecting requests says "Sign up", a shop says "Shop now". It is not
always right: the same goal serves a driving school taking applications and
a restaurant taking bookings, and the word on the button is the last thing
somebody reads before they tap.

**Keyed by where the tap lands, not by the goal.** Which buttons the
provider accepts follows the destination - an advert that dials a number
takes one word and nothing else - and a table keyed by goal would have to
repeat every website row for every website goal, then drift.

The catalogue's own choice stays the default. Nothing here reorders the
list to put it first: a person reading the buttons is reading them in the
order they would say them, and the ticked one is marked rather than moved.

Provider vocabulary, like the tables beside it: ``key`` is what gets sent,
``provider_label`` is what the provider's own screen calls it, and what the
owner reads is decided above this package.
"""

from dataclasses import dataclass
from typing import Final

from core.targeting.destinations import AdDestination


@dataclass(frozen=True, slots=True)
class AdButton:
    """One button an advert may carry."""

    provider: str
    key: str
    provider_label: str


# What the provider offers for each destination. Only buttons it accepts on
# an advert built here: a word it refuses arrives as a refusal on the last
# call of the sequence, with a campaign, an ad set and an upload already
# made.
BUTTONS: Final[dict[tuple[str, AdDestination], tuple[AdButton, ...]]] = {
    ("meta", "website"): (
        AdButton("meta", "LEARN_MORE", "Learn more"),
        AdButton("meta", "SHOP_NOW", "Shop now"),
        AdButton("meta", "SIGN_UP", "Sign up"),
        AdButton("meta", "ORDER_NOW", "Order now"),
        AdButton("meta", "BOOK_TRAVEL", "Book now"),
        AdButton("meta", "APPLY_NOW", "Apply now"),
        AdButton("meta", "GET_QUOTE", "Get quote"),
        AdButton("meta", "GET_OFFER", "Get offer"),
        AdButton("meta", "CONTACT_US", "Contact us"),
        AdButton("meta", "SUBSCRIBE", "Subscribe"),
        AdButton("meta", "DOWNLOAD", "Download"),
        AdButton("meta", "SEE_MENU", "See menu"),
        AdButton("meta", "GET_DIRECTIONS", "Get directions"),
    ),
    # A form the provider hosts. The tap opens it rather than a page, so
    # the words that promise a page - "See menu", "Get directions" - are
    # not here even though the provider would accept them.
    ("meta", "form"): (
        AdButton("meta", "SIGN_UP", "Sign up"),
        AdButton("meta", "LEARN_MORE", "Learn more"),
        AdButton("meta", "APPLY_NOW", "Apply now"),
        AdButton("meta", "BOOK_TRAVEL", "Book now"),
        AdButton("meta", "GET_QUOTE", "Get quote"),
        AdButton("meta", "GET_OFFER", "Get offer"),
        AdButton("meta", "SUBSCRIBE", "Subscribe"),
        AdButton("meta", "DOWNLOAD", "Download"),
    ),
    # A conversation. Both words the provider has for it, and they are not
    # interchangeable: the second is the one it accepts on an Instagram
    # advert - see :mod:`core.targeting.destinations`.
    ("meta", "chat"): (
        AdButton("meta", "SEND_MESSAGE", "Send message"),
        AdButton("meta", "LEARN_MORE", "Learn more"),
    ),
}

# A dialled number, an advert with no button at all, and the profile. One
# word each, so there is nothing to choose and nothing is offered: a list of
# one is a step rather than a choice.
#
# The profile's word is Meta's API name for Ads Manager's «Visit Instagram
# profile» - the profile visit ads guide requires it and no other.
FIXED_BUTTONS: Final[dict[AdDestination, str]] = {
    "phone": "CALL_NOW",
    "nothing": "NO_BUTTON",
    "profile": "VIEW_INSTAGRAM_PROFILE",
}


def buttons_for(*, provider: str, sends_to: AdDestination) -> tuple[AdButton, ...]:
    """Every button this kind of advert may carry. Empty when there is no choice."""
    return BUTTONS.get((provider, sends_to), ())


def button(*, provider: str, sends_to: AdDestination, key: str) -> AdButton | None:
    """The named button if this advert may carry it, ``None`` otherwise.

    ``None`` rather than a fallback, like a conversion event and unlike a
    campaign kind: a word the provider refuses costs the whole sequence,
    and the catalogue's own is what the caller keeps instead.
    """
    for row in buttons_for(provider=provider, sends_to=sends_to):
        if row.key == key:
            return row
    return None


__all__ = ["BUTTONS", "FIXED_BUTTONS", "AdButton", "button", "buttons_for"]
