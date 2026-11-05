"""What can go wrong before the domain is ever reached."""


class PaymentError(Exception):
    """Base for everything this package raises."""


class ProviderNotRegistered(PaymentError):
    """No adapter is registered under that name."""


class ProviderMisconfigured(PaymentError):
    """The adapter was built without something it cannot work without."""


class ProviderUnavailable(PaymentError):
    """The provider could not be reached, or refused a call we made to it."""


class ProviderRefused(ProviderUnavailable):
    """The provider answered and said no; ``code`` is its own word for why."""

    def __init__(self, message: str, *, code: str = "", details: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class OutcomeUnknown(ProviderUnavailable):
    """The request left and no answer came back: it may have been done."""


class MalformedCallback(PaymentError):
    """The body did not parse as this provider's own protocol."""


__all__ = [
    "MalformedCallback",
    "OutcomeUnknown",
    "PaymentError",
    "ProviderMisconfigured",
    "ProviderNotRegistered",
    "ProviderRefused",
    "ProviderUnavailable",
]
