"""Multicard's (Rahmat's) vocabulary, in one file."""

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

PRODUCTION_URL: Final = "https://mesh.multicard.uz"
SANDBOX_URL: Final = "https://dev-mesh.multicard.uz"

# Multicard counts in tiyin: two places, whatever the invoice's own currency
# carries. Only so'm is taken.
TIYIN_PLACES: Final = 2
CURRENCY: Final = "UZS"

# Where Multicard's callbacks come from, per its documentation.
CALLBACK_IP: Final = "195.158.26.90"

# How long before the token's own expiry a new one is asked for.
TOKEN_MARGIN_SECONDS: Final = 120
# The token's expiry is written in Tashkent time.
TOKEN_ZONE: Final = "Asia/Tashkent"

LANGUAGES: Final = frozenset({"ru", "uz", "en"})

# The payment-status webhook's statuses, and what each means to an invoice.
SUCCESS: Final = "success"
REVERT: Final = "revert"

# What the payer reads on Multicard's failed-payment page. The callback is
# answered before the money moves, so a refusal here returns it to the card.
MESSAGES: Final[dict[Refusal, str]] = {
    UNAUTHORIZED: "So'rov imzosi noto'g'ri.",
    MALFORMED: "So'rovni o'qib bo'lmadi.",
    INVOICE_NOT_FOUND: "Hisob topilmadi.",
    INVOICE_NOT_PAYABLE: "Bu hisobni to'lab bo'lmaydi: muddati o'tgan yoki allaqachon to'langan.",
    INVOICE_HELD: "Bu hisob boshqa to'lov bilan band.",
    AMOUNT_MISMATCH: "To'lov summasi hisobdagi summaga mos emas.",
    TRANSACTION_NOT_FOUND: "To'lov topilmadi.",
    STATE_NOT_ALLOWED: "To'lov holati bu amalga ruxsat bermaydi.",
    TIMED_OUT: "To'lov vaqti tugadi.",
    INTERNAL: "Ichki xato. Birozdan so'ng qayta urinib ko'ring.",
}
OK_MESSAGE: Final = "OK"

__all__ = [
    "CALLBACK_IP",
    "CURRENCY",
    "LANGUAGES",
    "MESSAGES",
    "OK_MESSAGE",
    "PRODUCTION_URL",
    "REVERT",
    "SANDBOX_URL",
    "SUCCESS",
    "TIYIN_PLACES",
    "TOKEN_MARGIN_SECONDS",
    "TOKEN_ZONE",
]
