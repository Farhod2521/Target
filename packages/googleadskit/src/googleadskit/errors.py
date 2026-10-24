"""Google Ads failures as this package reads them, before the domain does."""

from dataclasses import dataclass


class GoogleAdsError(Exception):
    """Base for anything that went wrong while talking to Google Ads."""


class GoogleAdsUnreachable(GoogleAdsError):
    """The request never reached Google. Repeating it is safe."""


class GoogleAdsOutcomeUnknown(GoogleAdsError):
    """The request left and no answer came back. A write may have landed."""


@dataclass(frozen=True, slots=True)
class FailureReason:
    """One entry of a ``GoogleAdsFailure``: its category and reason."""

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
        self.status = status
        self.reasons = reasons
        self.request_id = request_id
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
