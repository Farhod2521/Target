"""Provider-independent failures."""

from adskit.dto import RetiredOptionDTO


class AdsError(Exception):
    """Root of everything this package raises."""


class ProviderNotRegistered(AdsError):
    """``registry.get`` was asked for a provider nobody registered."""


class PortNotAvailable(AdsError):
    """A provider is registered, but cannot do this yet."""

    def __init__(self, *, provider: str, port: str) -> None:
        super().__init__(f"{provider} cannot do {port} yet")
        self.provider = provider
        self.port = port


class ProviderError(AdsError):
    """A call to a provider failed."""

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        user_title: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.user_title = user_title
        self.user_message = user_message


class AuthFailed(ProviderError):
    """The token is expired, revoked, or was never valid."""


class PermissionDenied(ProviderError):
    """The token is valid but lacks the scope, or the app lacks the review."""


class InvalidRequest(ProviderError):
    """The provider rejected the payload."""


class NotFound(ProviderError):
    """The object is gone, or was never visible to this token."""


class TermsNotAccepted(ProviderError):
    """The provider is waiting for the advertiser to agree to something."""


class AccountActionRequired(ProviderError):
    """The advertising account is held until its owner does something."""


class BudgetTooLow(ProviderError):
    """The daily budget is under the floor this provider enforces."""


class PaymentMethodMissing(ProviderError):
    """The ad account has no payment method the provider will charge."""


class LeadFormPrivacyMissing(ProviderError):
    """The lead form on the ad links to no privacy policy."""


class BidStrategyRefused(ProviderError):
    """The provider will not buy this goal with the bid strategy sent."""


class LocationNotRecognized(ProviderError):
    """The audience names a place the provider does not recognise."""


class LocationsOverlap(ProviderError):
    """Two of the audience's places cover the same ground."""


class MediaTooLarge(ProviderError):
    """The provider would not take the file in the request it was sent in."""


class TargetingOptionRetired(ProviderError):
    """The audience names a catalogue entry the provider has withdrawn."""

    def __init__(
        self,
        message: str,
        *,
        retired: tuple[RetiredOptionDTO, ...] = (),
        code: str = "",
        user_title: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(
            message, code=code, user_title=user_title, user_message=user_message
        )
        self.retired = retired


class RateLimited(ProviderError):
    """The call budget is spent or close to it."""

    retryable = True

    def __init__(
        self, message: str, *, code: str = "", retry_after_seconds: int = 0
    ) -> None:
        super().__init__(message, code=code)
        self.retry_after_seconds = retry_after_seconds


class TemporaryFailure(ProviderError):
    """A transient fault: a 5xx, a timeout, a connection reset."""

    retryable = True


class ResultTruncated(ProviderError):
    """The provider had more rows than the read was allowed to fetch."""

    retryable = True

    def __init__(
        self, message: str, *, code: str = "", rows_read: int = 0, pages: int = 0
    ) -> None:
        super().__init__(message, code=code)
        self.rows_read = rows_read
        self.pages = pages
