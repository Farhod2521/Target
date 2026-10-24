"""Click's vocabulary, in one file."""

from typing import Final

from paykit.refs import (
    AMOUNT_MISMATCH,
    INTERNAL,
    INVOICE_HELD,
    INVOICE_NOT_FOUND,
    INVOICE_NOT_PAYABLE,
    MALFORMED,
    STATE_NOT_ALLOWED,
    TIMED_OUT,
    TRANSACTION_NOT_FOUND,
    UNAUTHORIZED,
    Refusal,
)

CHECKOUT_URL: Final = "https://my.click.uz/services/pay"

ACTION_PREPARE: Final = 0
ACTION_COMPLETE: Final = 1

OK: Final = 0

ERROR_CODES: Final[dict[Refusal, int]] = {
    UNAUTHORIZED: -1,
    AMOUNT_MISMATCH: -2,
    MALFORMED: -3,
    INVOICE_NOT_PAYABLE: -4,
    INVOICE_HELD: -4,
    INVOICE_NOT_FOUND: -5,
    TRANSACTION_NOT_FOUND: -6,
    INTERNAL: -7,
    STATE_NOT_ALLOWED: -9,
    TIMED_OUT: -9,
}

ERROR_NOTES: Final[dict[Refusal, str]] = {
    UNAUTHORIZED: "SIGN CHECK FAILED",
    AMOUNT_MISMATCH: "Incorrect parameter amount",
    MALFORMED: "Action not found",
    INVOICE_NOT_PAYABLE: "Already paid",
    INVOICE_HELD: "Already paid",
    INVOICE_NOT_FOUND: "User does not exist",
    TRANSACTION_NOT_FOUND: "Transaction does not exist",
    INTERNAL: "Failed to update user",
    STATE_NOT_ALLOWED: "Transaction cancelled",
    TIMED_OUT: "Transaction cancelled",
}

SUCCESS_NOTE: Final = "Success"

PREPARE_SIGNED: Final = (
    "click_trans_id",
    "service_id",
    "merchant_trans_id",
    "amount",
    "action",
    "sign_time",
)
COMPLETE_SIGNED: Final = (
    "click_trans_id",
    "service_id",
    "merchant_trans_id",
    "merchant_prepare_id",
    "amount",
    "action",
    "sign_time",
)

SECRET_AFTER: Final = "service_id"


__all__ = [
    "ACTION_COMPLETE",
    "ACTION_PREPARE",
    "CHECKOUT_URL",
    "COMPLETE_SIGNED",
    "ERROR_CODES",
    "ERROR_NOTES",
    "OK",
    "PREPARE_SIGNED",
    "SECRET_AFTER",
    "SUCCESS_NOTE",
]
