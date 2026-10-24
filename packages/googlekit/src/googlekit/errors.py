"""Google API failures, split by what the caller should do about them.

Three of the answers change stored state, because nothing works until a
person acts:

* :class:`AccessRevoked` - the permission was taken back, or Google let
  the grant lapse. The person has to connect again.
* :class:`PermissionMissing` - the token is alive but may not touch this.
  On a ``drive.file`` grant that is a file this app did not create, or a
  box unticked on the consent screen.
* :class:`SheetMissing` - the spreadsheet, or the tab inside it, is gone.

The rest pass on their own, and all of them are :class:`Unavailable`.
One of those matters more than any of the above: :class:`OutcomeUnknown`,
a request that left and whose answer never came back. A write that ends
that way may have happened, and retrying it blindly is how a row appears
twice - so it has a class of its own, and a caller that does not care can
still catch it as :class:`Unavailable`.

**A 401 is temporary here, on purpose.** An access token lives an hour
and every caller refreshes before it writes, so a 401 is a token that ran
out between the two. The refresh that follows is what answers, with
authority, whether the grant itself is gone - reading a 401 as revocation
would send somebody to reconnect over a clock.

**Not every 403 is the person's.** An API switched off in the Cloud
project answers 403 too, and that one is :class:`GoogleAPIError`: this
deployment's to fix, and nothing the person could reach.

No message here carries a credential. Google takes the token in a header,
which no exception prints, and nothing below copies a request body.
"""

from collections.abc import Mapping
from typing import Any, Final

# Every reason Google gives, in either of its two error shapes, for "slow
# down". Sheets answers 429, but Drive still sends some of these as 403 -
# and a 403 read as a permission problem would break a link over a busy
# minute.
RATE_REASONS: Final = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"}
)

# How Google says one of its APIs is switched off for the Cloud project. A
# 403, the status a missing permission also gets - but it is this
# deployment's setup rather than the person's grant. Read as theirs, one
# API left unticked in the console would stop every link at once and make
# a new file on every reconnect.
SETUP_REASONS: Final = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})

# How Sheets says a tab id does not exist: a 400 rather than a 404, and
# only the message tells it apart from a request that was malformed.
_NO_GRID: Final = "no grid with id"

_MESSAGE_MAX_CHARS: Final = 300


class GoogleError(Exception):
    """Base for anything that went wrong while talking to Google."""


class GoogleAPIError(GoogleError):
    """Google refused the request as written, or our Cloud setup: ours to fix."""


class AccessRevoked(GoogleError):
    """The grant is gone. Nothing works until the person connects again."""


class PermissionMissing(GoogleError):
    """The token works, just not on this."""


class SheetMissing(GoogleError):
    """The spreadsheet, or the tab being written to, was deleted."""


class TabMissing(SheetMissing):
    """The file is there; the tab being written to was deleted.

    A kind of ``SheetMissing``, so a caller that only asks "is it gone"
    reads both alike. Apart because the fixes differ: a lost tab can be
    added back to the same file, and a lost file cannot.
    """


class Unavailable(GoogleError):
    """Google did not answer usefully this time. Try again later."""


class RateLimited(Unavailable):
    """Too many requests in this minute."""


class OutcomeUnknown(Unavailable):
    """The request left and no answer came back. It may have happened."""


def translate(*, status: int, payload: Mapping[str, Any]) -> GoogleError:
    """One failed answer, as the class its caller acts on."""
    error = payload.get("error")
    if isinstance(error, str):
        return _oauth_error(status=status, code=error, payload=payload)

    info: Mapping[str, Any] = error if isinstance(error, Mapping) else {}
    message = _short(str(info.get("message") or f"HTTP {status}"))
    reasons = _reasons(info)
    if status == 429 or reasons & RATE_REASONS:
        return RateLimited(message)
    if status >= 500 or status == 401:
        return Unavailable(message)
    if status == 400 and _NO_GRID in message.lower():
        return TabMissing(message)
    if status == 404:
        return SheetMissing(message)
    if status == 403 and not reasons & SETUP_REASONS:
        return PermissionMissing(message)
    return GoogleAPIError(message)


def _oauth_error(*, status: int, code: str, payload: Mapping[str, Any]) -> GoogleError:
    """The token endpoint's own shape: ``{"error": "invalid_grant", ...}``.

    ``invalid_grant`` is the only answer about the person. Every other one
    - a wrong client secret, a redirect that does not match - is about
    this deployment, and breaking a customer's link over our configuration
    would send them to fix something they cannot reach.
    """
    description = _short(str(payload.get("error_description") or ""))
    if code == "invalid_grant":
        return AccessRevoked(f"invalid_grant: {description}")
    if status >= 500:
        return Unavailable(f"{code}: {description}")
    return GoogleAPIError(f"{code}: {description}")


def _reasons(info: Mapping[str, Any]) -> frozenset[str]:
    """Every ``reason`` in the answer, from both of Google's error shapes.

    The older one lists ``errors[].reason``; the newer one attaches a
    ``google.rpc.ErrorInfo`` under ``details``. Sheets and Drive do not
    agree on which to send, so both are read.
    """
    found: set[str] = set()
    for key in ("errors", "details"):
        for item in info.get(key) or ():
            if isinstance(item, Mapping) and item.get("reason"):
                found.add(str(item["reason"]))
    if info.get("status") == "RESOURCE_EXHAUSTED":
        found.add("RATE_LIMIT_EXCEEDED")
    return frozenset(found)


def _short(text: str) -> str:
    """A message small enough to be worth logging whole."""
    return text[:_MESSAGE_MAX_CHARS]


__all__ = [
    "RATE_REASONS",
    "SETUP_REASONS",
    "AccessRevoked",
    "GoogleAPIError",
    "GoogleError",
    "OutcomeUnknown",
    "PermissionMissing",
    "RateLimited",
    "SheetMissing",
    "Unavailable",
    "translate",
]
