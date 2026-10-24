"""What can go wrong before the domain is ever reached.

Three of these, and none of them describe a payment. A payment that cannot
proceed is answered with a :data:`~paykit.refs.Refusal` and a proper
provider response - the caller has an invoice to explain and a body to
return. These are the failures where there is nothing to answer *with*:
the credential is missing, the request is not from the provider, or the
body is not the shape the provider documents.
"""


class PaymentError(Exception):
    """Base for everything this package raises."""


class ProviderNotRegistered(PaymentError):
    """No adapter is registered under that name.

    A startup bug, always. It means the deployment offered a provider on a
    screen and never wired it in, or a stored invoice names a provider that
    was switched off after it was created - and the second one is the
    reason this is raised rather than answered ``None``: a silent miss here
    would let a callback for a live payment fall through to a 404.
    """


class ProviderMisconfigured(PaymentError):
    """The adapter was built without something it cannot work without.

    Raised at construction, not at the first callback. A merchant id that
    is an empty string produces a checkout link that looks fine, sends the
    payer to a page that refuses them, and tells nobody why - so the
    adapter refuses to exist instead.
    """


class MalformedCallback(PaymentError):
    """The body did not parse as this provider's own protocol.

    Distinct from a refusal: a refusal is a request we understood and will
    not honour, and it is answered inside the provider's envelope. This is
    a request we could not read well enough to build an envelope from, and
    the adapter answers it with its own fixed "bad request" body - see
    ``refuse_malformed`` on the port.
    """


__all__ = [
    "MalformedCallback",
    "PaymentError",
    "ProviderMisconfigured",
    "ProviderNotRegistered",
]
