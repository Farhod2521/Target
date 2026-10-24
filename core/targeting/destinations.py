"""Where an ad sends the person who taps it - in the domain's own words."""

from dataclasses import dataclass
from typing import Final, Literal

AdDestination = Literal[
    "form", "website", "phone", "chat", "store", "nothing", "profile"
]

DESTINATIONS: Final[frozenset[str]] = frozenset(
    {"form", "website", "phone", "chat", "store", "nothing", "profile"}
)

DELIVERABLE: Final[frozenset[str]] = frozenset(
    {"form", "website", "chat", "phone", "nothing", "profile"}
)


ChatChannel = Literal["messenger", "instagram"]


@dataclass(frozen=True, slots=True)
class Channel:
    """One surface, and the two provider words that go with it."""

    destination_type: str
    call_to_action: str


CHANNELS: Final[dict[str, Channel]] = {
    "messenger": Channel(destination_type="MESSENGER", call_to_action="MESSAGE_PAGE"),
    "instagram": Channel(
        destination_type="INSTAGRAM_DIRECT", call_to_action="INSTAGRAM_MESSAGE"
    ),
}

DEFAULT_CHAT_CHANNEL: Final[ChatChannel] = "messenger"


def channel(name: str) -> Channel:
    """The surface behind a channel name, falling back to the safe one."""
    return CHANNELS.get(name, CHANNELS[DEFAULT_CHAT_CHANNEL])


def is_deliverable(destination: str) -> bool:
    """Whether the sequence can build an ad that lands here."""
    return destination in DELIVERABLE


def needs_lead_form(destination: str) -> bool:
    """Whether a lead form has to be created and hung on the creative."""
    return destination == "form"


def opens_chat(destination: str) -> bool:
    """Whether tapping the ad opens a conversation rather than a page."""
    return destination == "chat"


def needs_link(destination: str) -> bool:
    """Whether the ad has to carry the advertiser's own address."""
    return destination == "website"


def needs_phone(destination: str) -> bool:
    """Whether the ad has to carry a number the tap dials."""
    return destination == "phone"


def shows_a_button(destination: str) -> bool:
    """Whether there is anywhere for a button to send anybody."""
    return destination != "nothing"


def opens_profile(destination: str) -> bool:
    """Whether tapping the ad opens the business's Instagram profile."""
    return destination == "profile"
