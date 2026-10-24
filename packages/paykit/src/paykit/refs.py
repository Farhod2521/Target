"""Names for the values that cross the line between a provider and us.

``NewType`` rather than bare ``str`` and ``int``, for the reason the ads
side gives: the two identifiers in this package look identical to a type
checker and mixing them is the mistake that credits the wrong invoice.
"""

from typing import Literal, NewType

# The word a provider is registered under: ``"payme"``, ``"click"``.
# Never compared anywhere except the registry - see :mod:`paykit.registry`.
ProviderName = NewType("ProviderName", str)

# Money, as an integer count of the currency's smallest unit. Never a
# float and never a decimal: a subscription price that drifts by a
# hundredth is a reconciliation somebody does by hand.
MinorUnits = NewType("MinorUnits", int)

# What the payer is charged against - our number for one invoice, short
# enough to be read out over the phone. It travels into the provider's
# own "account" field and comes back on every callback.
InvoiceNumber = NewType("InvoiceNumber", str)

# The provider's identifier for one payment attempt. A string, never an
# integer: Payme's is a Mongo object id and nothing promises the next
# provider uses digits.
ExternalId = NewType("ExternalId", str)


# Where one payment attempt sits. Four states and not three, because the
# fourth is the one that costs money: a payment cancelled *after* it was
# taken is a refund, and it has to shorten a subscription that a payment
# cancelled before it was taken never lengthened.
TransactionState = Literal["created", "performed", "canceled", "refunded"]

CREATED: TransactionState = "created"
PERFORMED: TransactionState = "performed"
CANCELED: TransactionState = "canceled"
REFUNDED: TransactionState = "refunded"


# How a payer reaches the provider. Two shapes, because two exist in this
# market: a card gateway hands over a URL to open, and an agent network
# hands over a number the payer quotes at a counter or types into an app.
#
# Named constants rather than bare strings so the screen that branches on
# this is branching on a value the package defines - the alternative is a
# literal in a template that nothing checks against the adapters.
CheckoutKind = Literal["redirect", "reference"]

REDIRECT: CheckoutKind = "redirect"
REFERENCE: CheckoutKind = "reference"


# What a provider was asked to do, in words that are not any one
# provider's. Payme sends six JSON-RPC methods, Click sends two form posts
# with an ``action`` in them, and both reduce to these.
#
#   CHECK      may this invoice be paid at all
#   CREATE     hold this attempt; the payer is at the provider's screen
#   PERFORM    the money moved - deliver what was bought
#   CANCEL     it did not move, or it moved and is going back
#   STATUS     what became of the attempt you were told about
#   STATEMENT  every attempt in this window, so the provider can reconcile
Command = Literal["check", "create", "perform", "cancel", "status", "statement"]

CHECK: Command = "check"
CREATE: Command = "create"
PERFORM: Command = "perform"
CANCEL: Command = "cancel"
STATUS: Command = "status"
STATEMENT: Command = "statement"


# Why a request was refused, in the same provider-neutral vocabulary. The
# adapter turns one of these into whatever number its provider expects -
# which is the whole reason the numbers are not in the domain.
#
# ``AMOUNT_MISMATCH`` deserves its own name rather than folding into
# ``INVOICE_NOT_PAYABLE``: it is the one refusal that means somebody
# tampered with a checkout link, and an operator looking at a run of them
# is looking at an attack rather than at a bug.
#
# ``INVOICE_HELD`` is split out of it for a different reason: a bill
# another attempt is holding is a clash between two attempts, not a bill
# that cannot be paid, and a provider can ask for the two to be told
# apart.
Refusal = Literal[
    "unauthorized",
    "malformed",
    "invoice_not_found",
    "invoice_not_payable",
    "invoice_held",
    "amount_mismatch",
    "transaction_not_found",
    "state_not_allowed",
    "timed_out",
    "internal",
]

UNAUTHORIZED: Refusal = "unauthorized"
MALFORMED: Refusal = "malformed"
INVOICE_NOT_FOUND: Refusal = "invoice_not_found"
INVOICE_NOT_PAYABLE: Refusal = "invoice_not_payable"
INVOICE_HELD: Refusal = "invoice_held"
AMOUNT_MISMATCH: Refusal = "amount_mismatch"
TRANSACTION_NOT_FOUND: Refusal = "transaction_not_found"
STATE_NOT_ALLOWED: Refusal = "state_not_allowed"
TIMED_OUT: Refusal = "timed_out"
INTERNAL: Refusal = "internal"


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
    "CheckoutKind",
    "Command",
    "ExternalId",
    "InvoiceNumber",
    "MinorUnits",
    "ProviderName",
    "Refusal",
    "TransactionState",
]
