"""What can go wrong before the domain is ever reached."""


class PaymentError(Exception):
    """Base for everything this package raises."""


class ProviderNotRegistered(PaymentError):
    """No adapter is registered under that name."""


class ProviderMisconfigured(PaymentError):
    """The adapter was built without something it cannot work without."""


class MalformedCallback(PaymentError):
    """The body did not parse as this provider's own protocol."""


__all__ = [
    "MalformedCallback",
    "PaymentError",
    "ProviderMisconfigured",
    "ProviderNotRegistered",
]
