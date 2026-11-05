"""The one capability a payment provider must offer."""

from typing import Protocol, runtime_checkable

from paykit.dto import (
    CallbackRequest,
    Checkout,
    CheckoutRequest,
    Outcome,
    ProviderResponse,
    RawRequest,
)
from paykit.refs import ProviderName


@runtime_checkable
class PaymentPort(Protocol):
    """Send a payer to a provider, and answer that provider afterwards."""

    @property
    def name(self) -> ProviderName:
        """The word this adapter is registered under."""
        ...

    def checkout(self, *, request: CheckoutRequest) -> Checkout:
        """Where to send the payer for this invoice."""
        ...

    def authenticate(self, *, request: RawRequest) -> bool:
        """Whether this request really came from the provider."""
        ...

    def parse(self, *, request: RawRequest) -> CallbackRequest:
        """Read the provider's request as a command about one invoice."""
        ...

    def render(self, *, request: CallbackRequest, outcome: Outcome) -> ProviderResponse:
        """The body this provider expects for that decision."""
        ...

    def refuse_unauthenticated(self, *, request: RawRequest) -> ProviderResponse:
        """The answer to a request that did not authenticate."""
        ...

    def refuse_malformed(self, *, request: RawRequest) -> ProviderResponse:
        """The answer to a request this protocol cannot read."""
        ...


@runtime_checkable
class RefundPort(Protocol):
    """A provider that can be asked from here to return a payment.

    Its word that a payment was returned comes in a request whose signature
    may not cover that word, so it is believed only once read back.
    """

    def reverted(self, *, external_id: str) -> bool:
        """Whether the provider holds this payment as returned to the card."""
        ...

    def refund(self, *, external_id: str) -> None:
        """Return the whole payment to the card; nothing if it already was."""
        ...


__all__ = ["PaymentPort", "RefundPort"]
