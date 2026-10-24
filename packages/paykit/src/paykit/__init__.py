"""Taking money for a subscription, without the domain learning a provider.

Three providers, one port and no HTTP client. That last part is the shape
of this market: a payer is sent to a page built from a merchant id and an
amount, and everything that follows is the provider making requests to
*us*. So this package is mostly a reader of other people's HTTP requests
and a writer of the bodies they expect back.

**What is abstracted is the conversation, not the protocol.** Payme speaks
six JSON-RPC methods, Click posts two signed forms, and an agent network
does neither. Underneath they ask the same six questions - may this be
paid, hold it, it is paid, it is cancelled, what happened, what happened
all week - and those six are :data:`~paykit.refs.Command`. Nothing above
this package has ever needed a seventh.

**Refusals are a domain vocabulary, not a number.** ``-31050``, ``-5`` and
``302`` all mean "no such invoice" to three different companies. The
domain answers ``invoice_not_found`` and the adapter picks the number,
which is what keeps a provider's error table out of a service - and out of
the next provider's service, which will have a different one.

**Nothing here reads a clock, an environment or a database.** Credentials
arrive at construction, times arrive as arguments, and the state of an
invoice arrives as a DTO. An adapter is a stateless translator, which is
what makes it testable with a dict and a byte string.
"""

from paykit.dto import (
    Allowed,
    CallbackRequest,
    Checkout,
    CheckoutRequest,
    Outcome,
    ProviderResponse,
    RawRequest,
    Refused,
    Settled,
    Statement,
    TransactionRecord,
)
from paykit.errors import (
    MalformedCallback,
    PaymentError,
    ProviderMisconfigured,
    ProviderNotRegistered,
)
from paykit.ports import PaymentPort
from paykit.refs import (
    AMOUNT_MISMATCH,
    CANCEL,
    CANCELED,
    CHECK,
    CREATE,
    CREATED,
    INTERNAL,
    INVOICE_HELD,
    INVOICE_NOT_FOUND,
    INVOICE_NOT_PAYABLE,
    MALFORMED,
    PERFORM,
    PERFORMED,
    REDIRECT,
    REFERENCE,
    REFUNDED,
    STATE_NOT_ALLOWED,
    STATEMENT,
    STATUS,
    TIMED_OUT,
    TRANSACTION_NOT_FOUND,
    UNAUTHORIZED,
    CheckoutKind,
    Command,
    ExternalId,
    InvoiceNumber,
    MinorUnits,
    ProviderName,
    Refusal,
    TransactionState,
)

__all__ = [
    "AMOUNT_MISMATCH",
    "CANCEL",
    "CANCELED",
    "CHECK",
    "CREATE",
    "CREATED",
    "INTERNAL",
    "INVOICE_HELD",
    "INVOICE_NOT_FOUND",
    "INVOICE_NOT_PAYABLE",
    "MALFORMED",
    "PERFORM",
    "PERFORMED",
    "REFUNDED",
    "STATEMENT",
    "STATE_NOT_ALLOWED",
    "STATUS",
    "TIMED_OUT",
    "TRANSACTION_NOT_FOUND",
    "UNAUTHORIZED",
    "Allowed",
    "CallbackRequest",
    "Checkout",
    "CheckoutRequest",
    "Command",
    "ExternalId",
    "InvoiceNumber",
    "MalformedCallback",
    "MinorUnits",
    "Outcome",
    "PaymentError",
    "PaymentPort",
    "ProviderMisconfigured",
    "ProviderName",
    "ProviderNotRegistered",
    "ProviderResponse",
    "RawRequest",
    "Refusal",
    "Refused",
    "Settled",
    "Statement",
    "TransactionRecord",
    "TransactionState",
]
