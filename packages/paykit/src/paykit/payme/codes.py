"""Payme's vocabulary, in one file.

Every number and every method name Payme publishes lives here and nowhere
else. That is the point of the file: when Payme changes a code, the change
is a line in a dict rather than a search through an adapter - and the
domain never learns any of them, because the adapter is what translates.

The error codes are Payme's own. The band -31050 to -31099 is explicitly
reserved for the merchant to define, which is where the two invoice
failures below sit; everything else is fixed by the protocol.
"""

from typing import Final

from paykit.refs import (
    AMOUNT_MISMATCH,
    CANCEL,
    CHECK,
    CREATE,
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

# The username half of the Basic credential. Fixed by Payme and the same
# for every merchant - the key is the secret, this is not.
BASIC_USER: Final = "Paycom"

# JSON-RPC method name to the command the domain understands. The one
# place the six names appear.
METHODS: Final[dict[str, Command]] = {
    "CheckPerformTransaction": CHECK,
    "CreateTransaction": CREATE,
    "PerformTransaction": PERFORM,
    "CancelTransaction": CANCEL,
    "CheckTransaction": STATUS,
    "GetStatement": STATEMENT,
}

# Payme's numbering for where an attempt sits. Two negatives, not one:
# -1 is cancelled before the money moved and -2 is cancelled after, and
# only the second one is a refund somebody has to be given service back
# for. That distinction is the reason ``refunded`` exists in the domain.
STATE_CREATED: Final = 1
STATE_PERFORMED: Final = 2
STATE_CANCELED: Final = -1
STATE_REFUNDED: Final = -2

# Protocol-level failures, before a command is even identified.
PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INSUFFICIENT_PRIVILEGE: Final = -32504

ERROR_CODES: Final[dict[Refusal, int]] = {
    UNAUTHORIZED: INSUFFICIENT_PRIVILEGE,
    MALFORMED: INVALID_REQUEST,
    # Merchant-defined band. Two codes rather than one because Payme shows
    # the message to the payer, and "we have no such invoice" and "that
    # invoice is already paid" send a person to two different places.
    INVOICE_NOT_FOUND: -31050,
    INVOICE_NOT_PAYABLE: -31051,
    AMOUNT_MISMATCH: -31001,
    TRANSACTION_NOT_FOUND: -31003,
    # "Unable to perform". Payme's one code for three domain answers, and
    # collapsing them here is correct: the payer is told the same thing,
    # and which of the three it was is in our own log.
    STATE_NOT_ALLOWED: -31008,
    # A second transaction for a bill another one is holding. Payme's
    # sandbox asks for exactly this code here, not one from the merchant
    # band - the payer typed nothing wrong.
    INVOICE_HELD: -31008,
    TIMED_OUT: -31008,
    INTERNAL: -31008,
}

# Payme renders the message to the payer in their own language, so the
# protocol requires all three. These are the provider's screen and not the
# product's, which is why they are here rather than in a Django catalogue -
# a package cannot reach one, and a translation loaded at render time
# would be the payer's language rather than the merchant's.
MESSAGES: Final[dict[Refusal, dict[str, str]]] = {
    UNAUTHORIZED: {
        "uz": "Ruxsat yo'q",
        "ru": "Нет доступа",
        "en": "Not authorised",
    },
    MALFORMED: {
        "uz": "So'rov noto'g'ri",
        "ru": "Неверный запрос",
        "en": "Malformed request",
    },
    INVOICE_NOT_FOUND: {
        "uz": "Bunday hisob topilmadi",
        "ru": "Счёт не найден",
        "en": "Invoice not found",
    },
    INVOICE_NOT_PAYABLE: {
        "uz": "Bu hisobni to'lash mumkin emas",
        "ru": "Этот счёт нельзя оплатить",
        "en": "This invoice cannot be paid",
    },
    INVOICE_HELD: {
        "uz": "Bu hisob boshqa to'lov bilan band",
        "ru": "Счёт уже оплачивается другой транзакцией",
        "en": "Another transaction is paying this invoice",
    },
    AMOUNT_MISMATCH: {
        "uz": "Summa noto'g'ri",
        "ru": "Неверная сумма",
        "en": "Wrong amount",
    },
    TRANSACTION_NOT_FOUND: {
        "uz": "Tranzaksiya topilmadi",
        "ru": "Транзакция не найдена",
        "en": "Transaction not found",
    },
    STATE_NOT_ALLOWED: {
        "uz": "Amalni bajarib bo'lmadi",
        "ru": "Операция невозможна",
        "en": "Unable to perform operation",
    },
    TIMED_OUT: {
        "uz": "Tranzaksiya muddati tugagan",
        "ru": "Срок транзакции истёк",
        "en": "Transaction timed out",
    },
    INTERNAL: {
        "uz": "Amalni bajarib bo'lmadi",
        "ru": "Операция невозможна",
        "en": "Unable to perform operation",
    },
}

# The refusals whose ``data`` field must name the account field Payme
# should highlight. Only the merchant-defined band carries one, and
# sending it on the others makes Payme's own validator complain.
FIELD_ERRORS: Final = frozenset({INVOICE_NOT_FOUND, INVOICE_NOT_PAYABLE})


__all__ = [
    "BASIC_USER",
    "ERROR_CODES",
    "FIELD_ERRORS",
    "INSUFFICIENT_PRIVILEGE",
    "INVALID_REQUEST",
    "MESSAGES",
    "METHODS",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "STATE_CANCELED",
    "STATE_CREATED",
    "STATE_PERFORMED",
    "STATE_REFUNDED",
]
