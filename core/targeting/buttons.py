"""The button on the advert, and which ones each kind of advert may carry."""

from dataclasses import dataclass
from typing import Final

from core.targeting.destinations import AdDestination


@dataclass(frozen=True, slots=True)
class AdButton:
    """One button an advert may carry."""

    provider: str
    key: str
    provider_label: str


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
    ("meta", "chat"): (
        AdButton("meta", "SEND_MESSAGE", "Send message"),
        AdButton("meta", "LEARN_MORE", "Learn more"),
    ),
}

FIXED_BUTTONS: Final[dict[AdDestination, str]] = {
    "phone": "CALL_NOW",
    "nothing": "NO_BUTTON",
    "profile": "VIEW_INSTAGRAM_PROFILE",
}


def buttons_for(*, provider: str, sends_to: AdDestination) -> tuple[AdButton, ...]:
    """Every button this kind of advert may carry. Empty when there is no choice."""
    return BUTTONS.get((provider, sends_to), ())


def button(*, provider: str, sends_to: AdDestination, key: str) -> AdButton | None:
    """The named button if this advert may carry it, ``None`` otherwise."""
    for row in buttons_for(provider=provider, sends_to=sends_to):
        if row.key == key:
            return row
    return None


__all__ = ["BUTTONS", "FIXED_BUTTONS", "AdButton", "button", "buttons_for"]
