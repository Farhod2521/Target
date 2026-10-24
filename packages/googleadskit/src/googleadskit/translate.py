"""Google Ads failures in the domain's own words.

The only module that knows Google's status words and error reasons. A
caller above this package catches :mod:`adskit.errors` and decides by class,
never by a Google string - the same anti-corruption layer ``metaads`` has
in :func:`metaads.adapter.translate_error`.

The coarse gRPC status decides first; the reason list refines it only
where Google's own documentation draws a line the status does not. An
account that is not enabled answers ``PERMISSION_DENIED`` like a missing
grant, and the two need different sentences: one is "connect again", the
other is "finish setting up the account in Google Ads".
"""

from typing import Final

from adskit.errors import (
    AccountActionRequired,
    AuthFailed,
    InvalidRequest,
    NotFound,
    PermissionDenied,
    ProviderError,
    RateLimited,
    TemporaryFailure,
)

from googleadskit.errors import (
    GoogleAdsAPIError,
    GoogleAdsError,
    GoogleAdsOutcomeUnknown,
)

# Statuses Google documents as worth another try with backoff.
_TRANSIENT_STATUSES: Final = frozenset(
    {"INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED", "ABORTED"}
)
_TRANSIENT_REASONS: Final = frozenset({"TRANSIENT_ERROR", "INTERNAL_ERROR"})

# The account exists and the grant is fine, but Google will not serve it
# until its owner acts in Google Ads: finishes signing up, accepts the
# terms, re-enables or un-suspends it.
_HELD_REASONS: Final = frozenset(
    {
        "CUSTOMER_NOT_ENABLED",
        "INCOMPLETE_SIGNUP",
        "MISSING_TOS",
        "ACTION_NOT_PERMITTED_FOR_SUSPENDED_ACCOUNT",
    }
)
# Refused because of this deployment's Cloud project, not the person's
# grant. Read as theirs, it would send every customer to reconnect over a
# setting only we can change.
_SETUP_REASONS: Final = frozenset(
    {
        "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION",
        "CLOUD_PROJECT_NOT_UNDER_ORGANIZATION",
        "PROJECT_DISABLED",
        "DEVELOPER_TOKEN_NOT_APPROVED",
        "DEVELOPER_TOKEN_NOT_ON_ALLOWLIST",
        "DEVELOPER_TOKEN_PROHIBITED",
    }
)


def translate_error(exc: GoogleAdsError) -> ProviderError:
    """One Google Ads failure as the domain's own error."""
    if isinstance(exc, GoogleAdsOutcomeUnknown):
        # Retryable for a read, which is all this package does today. A
        # write that ends this way may have landed; the code says so, and
        # a writer must look before it sends again.
        return TemporaryFailure(str(exc), code="outcome_unknown")
    if not isinstance(exc, GoogleAdsAPIError):
        return TemporaryFailure(str(exc), code="unreachable")

    code = _code(exc)
    if exc.status == "RESOURCE_EXHAUSTED" or exc.has("quotaError"):
        return RateLimited(
            str(exc), code=code, retry_after_seconds=exc.retry_after_seconds
        )
    if exc.has("authorizationError", *_SETUP_REASONS) or exc.has(
        "authenticationError", *_SETUP_REASONS
    ):
        return InvalidRequest(str(exc), code=code)
    if exc.status == "UNAUTHENTICATED" or exc.has("authenticationError"):
        return AuthFailed(str(exc), code=code)
    if exc.has("authorizationError", *_HELD_REASONS):
        return AccountActionRequired(str(exc), code=code)
    if exc.status == "PERMISSION_DENIED" or exc.has("authorizationError"):
        return PermissionDenied(str(exc), code=code)
    if exc.status == "NOT_FOUND":
        return NotFound(str(exc), code=code)
    if (
        exc.status in _TRANSIENT_STATUSES
        or exc.http_status >= 500
        or any(entry.reason in _TRANSIENT_REASONS for entry in exc.reasons)
    ):
        return TemporaryFailure(str(exc), code=code)
    return InvalidRequest(str(exc), code=code)


def _code(exc: GoogleAdsAPIError) -> str:
    """The most specific word Google gave, for logs and stored rows."""
    if exc.reasons:
        return exc.reasons[0].reason
    return exc.status or str(exc.http_status)


__all__ = ["translate_error"]
