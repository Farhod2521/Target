"""Names for the values that cross the line between a provider and us."""

from typing import Literal, NewType

ProviderName = NewType("ProviderName", str)

MinorUnits = NewType("MinorUnits", int)

InvoiceNumber = NewType("InvoiceNumber", str)

ExternalId = NewType("ExternalId", str)


TransactionState = Literal["created", "performed", "canceled", "refunded"]

CREATED: TransactionState = "created"
PERFORMED: TransactionState = "performed"
CANCELED: TransactionState = "canceled"
REFUNDED: TransactionState = "refunded"


CheckoutKind = Literal["redirect", "reference"]

REDIRECT: CheckoutKind = "redirect"
REFERENCE: CheckoutKind = "reference"


Command = Literal["check", "create", "perform", "cancel", "status", "statement"]

CHECK: Command = "check"
CREATE: Command = "create"
PERFORM: Command = "perform"
CANCEL: Command = "cancel"
STATUS: Command = "status"
STATEMENT: Command = "statement"


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
