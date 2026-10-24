"""Paynet's vocabulary, in one file - and provisionally."""

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

METHODS: Final[dict[str, Command]] = {
    "GetInformation": CHECK,
    "PerformTransaction": PERFORM,
    "CheckTransaction": STATUS,
    "CancelTransaction": CANCEL,
    "GetStatement": STATEMENT,
}

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
