"""Payme's vocabulary, in one file."""

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

BASIC_USER: Final = "Paycom"

METHODS: Final[dict[str, Command]] = {
    "CheckPerformTransaction": CHECK,
    "CreateTransaction": CREATE,
    "PerformTransaction": PERFORM,
    "CancelTransaction": CANCEL,
    "CheckTransaction": STATUS,
    "GetStatement": STATEMENT,
}

STATE_CREATED: Final = 1
STATE_PERFORMED: Final = 2
STATE_CANCELED: Final = -1
STATE_REFUNDED: Final = -2

PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INSUFFICIENT_PRIVILEGE: Final = -32504

ERROR_CODES: Final[dict[Refusal, int]] = {
    UNAUTHORIZED: INSUFFICIENT_PRIVILEGE,
    MALFORMED: INVALID_REQUEST,
    INVOICE_NOT_FOUND: -31050,
    INVOICE_NOT_PAYABLE: -31051,
    AMOUNT_MISMATCH: -31001,
    TRANSACTION_NOT_FOUND: -31003,
    STATE_NOT_ALLOWED: -31008,
    INVOICE_HELD: -31008,
    TIMED_OUT: -31008,
    INTERNAL: -31008,
}

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
