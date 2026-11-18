"""Whose a failure is, by the code a launch or a press was failed with.

One table for both. ``META``: Meta refused or the client's account must be
mended; Support takes it. ``PASSING``: it passes on its own or is one of our
own rules the screen already explains; nobody is told. ``SYSTEM``: our own
fault; it goes to the Developers with its logs, never to Support.
A code not named here is Meta's: Meta's raw numeric codes among them.
"""

from enum import StrEnum
from typing import Final

META_PROVIDER: Final = "meta"
# Meta's raw codes older rows were failed with, under the word our
# sentences are written for.
META_CODE_WORDS: Final[dict[str, str]] = {
    "190": "reconnect",
    "200": "permission",
    "10": "permission",
}


class FailureKind(StrEnum):
    META = "meta"
    PASSING = "passing"
    SYSTEM = "system"


PASSING_CODES: Final = frozenset(
    {
        # Meta busy or slow: pressing again works.
        "temporary",
        "rate_limited",
        "613",
        "4",
        "17",
        "32",
        # The object is already so, or no longer there.
        "already",
        "finished",
        "in_use",
        "gone",
        "not_found",
        "read",
        # Our own rules, told on the screen.
        "learning",
        "last_ad",
        "changed_elsewhere",
        "unchanged",
        # The client's own setup, not Meta's: the screen says what to fill.
        "subscription_expired",
        "free_proposals_used",
        "profile_incomplete",
        "site_missing",
        "site_unusable",
        "site_unreachable",
        "phone_missing",
    }
)
SYSTEM_CODES: Final = frozenset(
    {
        "unknown",
        "schema_error",
        "unavailable",
        "not_applied",
        "stalled",
        "prep_failed",
        "ai_failed",
        # What we built Meta could not have taken.
        "not_launchable",
    }
)


def kind_of(code: str | None) -> FailureKind:
    found = code or ""
    if found in SYSTEM_CODES:
        return FailureKind.SYSTEM
    if found in PASSING_CODES:
        return FailureKind.PASSING
    return FailureKind.META
