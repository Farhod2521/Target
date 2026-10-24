"""The one capability a payment provider must offer.

One port, not six. The ads side of this workspace has several because an
ad platform does several unrelated things; a payment provider does one
thing, in two halves - it takes the payer somewhere, and then it tells us
what happened. Splitting that into a ``CheckoutPort`` and a
``CallbackPort`` would produce two objects that are always registered
together, always configured from the same credential, and never useful
apart.

**The direction is the thing to notice.** Nothing here calls anybody. Four
of the six methods below turn somebody else's HTTP *request* into a
decision and back into a body, which is the opposite of how the ad ports
work and is why they could not have shared a shape.

An implementation is a stateless translator, like every adapter here. It
holds its merchant credentials - given at construction, never read from
the environment - and no connection, no clock and no database.
"""

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
        """The word this adapter is registered under.

        On the adapter rather than only in the registry, so a checkout it
        builds can name itself without the caller passing its own key back
        in - which is the shape that eventually disagrees.
        """
        ...

    def checkout(self, *, request: CheckoutRequest) -> Checkout:
        """Where to send the payer for this invoice.

        Built locally and offline. Every provider in this market encodes
        the merchant, the amount and the order into a URL or an account
        number, so a network call here would buy latency on a page a
        person is waiting on and nothing else.

        Raises nothing for an unpayable invoice: whether an invoice may be
        paid is the domain's question, asked before this is called.
        """
        ...

    def authenticate(self, *, request: RawRequest) -> bool:
        """Whether this request really came from the provider.

        A pure function of the bytes and the merchant secret, so it is
        testable without a request object - the rule the Meta webhook is
        already held to.

        **Called before anything is read out of the body, and before
        anything is written.** A body that has not authenticated is a body
        a stranger chose, and parsing one to decide how to answer it is
        how an unauthenticated caller learns which invoice numbers exist.
        """
        ...

    def parse(self, *, request: RawRequest) -> CallbackRequest:
        """Read the provider's request as a command about one invoice.

        Raises :class:`~paykit.errors.MalformedCallback` when the body is
        not this provider's protocol at all. A body that parses but names
        an invoice we do not have is *not* malformed - that is an ordinary
        refusal, and the difference matters because one of the two is
        answered inside the protocol and the other cannot be.
        """
        ...

    def render(self, *, request: CallbackRequest, outcome: Outcome) -> ProviderResponse:
        """The body this provider expects for that decision.

        ``request`` is passed back in because both protocols here need
        something echoed - a JSON-RPC id, a transaction number - and a
        renderer that had to be handed those separately would eventually
        be handed the wrong ones.
        """
        ...

    def refuse_unauthenticated(self, *, request: RawRequest) -> ProviderResponse:
        """The answer to a request that did not authenticate.

        Its own method because there is no :class:`CallbackRequest` to
        render against: the body was never read. Each provider documents a
        specific code for this and reads anything else as an outage.
        """
        ...

    def refuse_malformed(self, *, request: RawRequest) -> ProviderResponse:
        """The answer to a request this protocol cannot read.

        Authenticated, and still unreadable - which in practice means a
        protocol version changed under us. Answered inside the provider's
        own envelope where it has one, so the failure shows up in their
        dashboard rather than as an outage in ours.
        """
        ...


__all__ = ["PaymentPort"]
