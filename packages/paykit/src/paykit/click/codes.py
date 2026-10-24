"""Click's vocabulary, in one file.

The same arrangement as the Payme side and for the same reason: one place
to change when the provider republishes a number, and a domain that never
learns any of them.

Click's protocol is two form posts rather than six JSON-RPC methods, so
the interesting part here is not the method table - it is that the second
post carries the outcome in a field. ``error`` on an incoming *Complete*
is Click telling us what happened at their end, and a negative value there
means the payment did not go through. That is a cancel, not a failure to
answer, and reading it as anything else leaves a subscription switched on
for money that never moved.
"""

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

# Where a payer is sent. Configuration on the adapter, defaulted here.
CHECKOUT_URL: Final = "https://my.click.uz/services/pay"

# The two halves of Click's flow, as they arrive in the ``action`` field.
ACTION_PREPARE: Final = 0
ACTION_COMPLETE: Final = 1

# Success. Click reads any other value as a refusal and stops.
OK: Final = 0

ERROR_CODES: Final[dict[Refusal, int]] = {
    UNAUTHORIZED: -1,
    AMOUNT_MISMATCH: -2,
    # "Action not found" - the request named a step this protocol has no
    # answer for, which is Click's nearest thing to a malformed body.
    MALFORMED: -3,
    INVOICE_NOT_PAYABLE: -4,
    INVOICE_HELD: -4,
    INVOICE_NOT_FOUND: -5,
    TRANSACTION_NOT_FOUND: -6,
    INTERNAL: -7,
    STATE_NOT_ALLOWED: -9,
    TIMED_OUT: -9,
}

# What Click prints beside the code in its own dashboard. English, because
# that is the language of the protocol's published table and an operator
# comparing our reply with their documentation should see the same words.
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

# The fields signed on each of the two posts, in the order Click hashes
# them. The secret is spliced in after ``service_id`` - see the adapter.
#
# A tuple rather than a formatted string because the order is the whole
# security property: two fields swapped produces a digest that is wrong
# for every request, which looks exactly like a wrong secret key.
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

# Where the secret goes in both lists: straight after ``service_id``.
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
