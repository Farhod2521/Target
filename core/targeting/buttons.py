"""The button on the advert, and which ones each kind of advert may carry."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

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
    # No "chat" row: the chat's app picks the word (MESSAGE_PAGE,
    # INSTAGRAM_MESSAGE), so a word chosen here never reached Meta.
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


def kept_destination(*, current: Mapping[str, Any]) -> AdDestination | None:
    """What a running advert's button leads to, when another word may go on it.

    TZ 2.3: a new creative keeps where the advert leads and may change only the
    word. A form and a link take any word of their kind. A chat button names
    its app in the word itself (``INSTAGRAM_MESSAGE``, ``WHATSAPP_MESSAGE``),
    and a call or a profile has one word only - those stay as they are.
    """
    value = current.get("value")
    value = value if isinstance(value, Mapping) else {}
    if str(current.get("type") or "") in FIXED_BUTTONS.values():
        return None
    if value.get("lead_gen_form_id"):
        return "form"
    if value.get("app_destination"):
        return None
    if value.get("link"):
        return "website"
    return None


__all__ = [
    "BUTTONS",
    "FIXED_BUTTONS",
    "AdButton",
    "button",
    "buttons_for",
    "kept_destination",
]
