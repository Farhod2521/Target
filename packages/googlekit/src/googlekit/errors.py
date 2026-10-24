"""Google API failures, split by what the caller should do about them."""

from collections.abc import Mapping
from typing import Any, Final

RATE_REASONS: Final = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"}
)

SETUP_REASONS: Final = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})

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
    """The file is there; the tab being written to was deleted."""


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
    """The token endpoint's own shape: ``{"error": "invalid_grant", ...}``."""
    description = _short(str(payload.get("error_description") or ""))
    if code == "invalid_grant":
        return AccessRevoked(f"invalid_grant: {description}")
    if status >= 500:
        return Unavailable(f"{code}: {description}")
    return GoogleAPIError(f"{code}: {description}")


def _reasons(info: Mapping[str, Any]) -> frozenset[str]:
    """Every ``reason`` in the answer, from both of Google's error shapes."""
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
