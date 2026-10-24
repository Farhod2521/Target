"""Google Ads failures as this package reads them, before the domain does.

Google answers a refused request with one JSON shape: an HTTP status, a
gRPC status word (``UNAUTHENTICATED``, ``RESOURCE_EXHAUSTED`` ...) and a
``GoogleAdsFailure`` listing one or more errors, each with a category and
a reason (``authorizationError: USER_PERMISSION_DENIED``). All of it is
kept on :class:`GoogleAdsAPIError`; deciding what it means for a caller is
:mod:`googleadskit.translate`'s job, the one place that knows the words.

**Sent or not sent**, the same split ``googlekit`` makes. A failure before
the request reached Google is :class:`GoogleAdsUnreachable` and always safe
to repeat. A failure after it left - a read timeout, a dropped connection -
is :class:`GoogleAdsOutcomeUnknown`, because a write may have landed and
only its receipt was lost.

No message here carries a credential or a request body: the token travels
in a header no exception prints.
"""

from dataclasses import dataclass


class GoogleAdsError(Exception):
    """Base for anything that went wrong while talking to Google Ads."""


class GoogleAdsUnreachable(GoogleAdsError):
    """The request never reached Google. Repeating it is safe."""


class GoogleAdsOutcomeUnknown(GoogleAdsError):
    """The request left and no answer came back. A write may have landed."""


@dataclass(frozen=True, slots=True)
class FailureReason:
    """One entry of a ``GoogleAdsFailure``: its category and reason.

    ``category`` is the key Google used (``authorizationError``), ``reason``
    its value (``USER_PERMISSION_DENIED``). Both are kept as Google spells
    them so a log line can be pasted into a search box.
    """

    category: str
    reason: str


class GoogleAdsAPIError(GoogleAdsError):
    """Google answered and refused. Everything it said is kept."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int,
        status: str = "",
        reasons: tuple[FailureReason, ...] = (),
        request_id: str = "",
        retry_after_seconds: int = 0,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        # The gRPC canonical status word: the coarse answer, always present.
        self.status = status
        # The fine answer, present whenever the refusal came from Google Ads
        # itself rather than from the front door (a dead token is refused
        # before Google Ads sees the request, with no failure list at all).
        self.reasons = reasons
        # What Google's support asks for first. Logged, never shown.
        self.request_id = request_id
        # Only quota refusals carry it.
        self.retry_after_seconds = retry_after_seconds

    def has(self, category: str, *reasons: str) -> bool:
        """Whether any listed error is of ``category`` (and, if given, a reason)."""
        return any(
            entry.category == category and (not reasons or entry.reason in reasons)
            for entry in self.reasons
        )


__all__ = [
    "FailureReason",
    "GoogleAdsAPIError",
    "GoogleAdsError",
    "GoogleAdsOutcomeUnknown",
    "GoogleAdsUnreachable",
]
