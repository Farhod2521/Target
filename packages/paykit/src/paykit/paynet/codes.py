"""Paynet's vocabulary, in one file - and provisionally.

**Read this before trusting a number below.** Paynet's merchant contract is
not signed yet, and the two things a contract fixes are exactly the two
things in this file: what the methods are called, and which integer means
which refusal. Everything else in the adapter beside it - the JSON-RPC
envelope, the Basic credential, the parsing, the state machine - is
protocol shape that does not move.

So the numbers here are placeholders that follow Paynet's published
merchant tables as closely as they can be followed without the document
that comes with a cashbox. They are collected here precisely so that
reconciling them with the signed contract is an edit to two dicts rather
than a read of an adapter.

The other reason this provider is different: Paynet is an agent network
before it is a card gateway. A payer can settle an invoice at a counter,
in cash, by giving somebody a number - so there is nothing to redirect to,
and :meth:`~paykit.paynet.adapter.PaynetAdapter.checkout` answers with a
reference instead of a URL. That difference is why :class:`paykit.dto.
Checkout` has two shapes.
"""

from typing import Final

from paykit.refs import (
    AMOUNT_MISMATCH,
    CANCEL,
    CHECK,
    INTERNAL,
    INVOICE_HELD,
    INVOICE_NOT_FOUND,
    INVOICE_NOT_PAYABLE,
    MALFORMED,
    PERFORM,
    STATE_NOT_ALLOWED,
    STATEMENT,
    STATUS,
    TIMED_OUT,
    TRANSACTION_NOT_FOUND,
    UNAUTHORIZED,
    Command,
    Refusal,
)

# The username half of the Basic credential is the merchant's own login,
# so unlike Payme's it is configuration rather than a constant here.

# Method name to the command the domain understands.
#
# ``GetInformation`` is Paynet's check: it asks whether a number is one of
# ours and what it is for, before a cashier takes any money. There is no
# separate "hold this attempt" step in the counter flow - the money is
# handed over and ``PerformTransaction`` follows - which is why ``create``
# is absent from this table and the domain's create path is reached
# through perform instead.
METHODS: Final[dict[str, Command]] = {
    "GetInformation": CHECK,
    "PerformTransaction": PERFORM,
    "CheckTransaction": STATUS,
    "CancelTransaction": CANCEL,
    "GetStatement": STATEMENT,
}

# JSON-RPC transport failures, which are the protocol's and not Paynet's.
PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601

ERROR_CODES: Final[dict[Refusal, int]] = {
    UNAUTHORIZED: 401,
    MALFORMED: INVALID_REQUEST,
    INVOICE_NOT_FOUND: 302,
    INVOICE_NOT_PAYABLE: 411,
    INVOICE_HELD: 411,
    AMOUNT_MISMATCH: 303,
    TRANSACTION_NOT_FOUND: 201,
    STATE_NOT_ALLOWED: 202,
    TIMED_OUT: 203,
    INTERNAL: 500,
}

# English, like Click's notes and for the same reason: these appear in the
# provider's own console beside the code, and an operator comparing the
# two should read the same words in both.
ERROR_NOTES: Final[dict[Refusal, str]] = {
    UNAUTHORIZED: "Authentication failed",
    MALFORMED: "Invalid request",
    INVOICE_NOT_FOUND: "Invoice not found",
    INVOICE_NOT_PAYABLE: "Invoice cannot be paid",
    INVOICE_HELD: "Invoice cannot be paid",
    AMOUNT_MISMATCH: "Wrong amount",
    TRANSACTION_NOT_FOUND: "Transaction not found",
    STATE_NOT_ALLOWED: "Operation not allowed in this state",
    TIMED_OUT: "Transaction timed out",
    INTERNAL: "Internal error",
}


__all__ = [
    "ERROR_CODES",
    "ERROR_NOTES",
    "INVALID_REQUEST",
    "METHODS",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
]
