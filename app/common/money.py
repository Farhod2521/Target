from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from adskit import registry
from adskit.money import (
    ZERO_DECIMAL_CURRENCIES,
    MoneyRules,
    decimal_places,
    to_minor,
)

__all__ = [
    "CURRENCY_SIGNS",
    "ZERO_DECIMAL_CURRENCIES",
    "MoneyParts",
    "MoneyRules",
    "decimal_places",
    "format_minor",
    "format_minor_parts",
    "number_format",
    "provider_money",
    "to_major",
    "to_minor",
]

THOUSANDS: Final = " "
DECIMAL: Final = ","
CURRENCY_SIGNS: Final[dict[str, str]] = {"USD": "$", "EUR": "€"}


@dataclass(frozen=True, slots=True)
class MoneyParts:
    amount: str
    currency: str
    sign_first: bool = False

    def __str__(self) -> str:
        if self.sign_first:
            negative = self.amount.startswith("-")
            figure = self.amount.removeprefix("-")
            return f"{'-' if negative else ''}{self.currency}{figure}"
        return f"{self.amount} {self.currency}".strip()


def provider_money(*, provider: str) -> MoneyRules:
    return registry.get(provider).money


def to_major(*, amount_minor: int | None, places: int) -> Decimal | None:
    if amount_minor is None:
        return None
    return Decimal(amount_minor).scaleb(-places)


def number_format(value: Decimal | int | float, *, decimal_pos: int = 0) -> str:
    text = f"{Decimal(value):,.{decimal_pos}f}"
    return text.replace(",", THOUSANDS).replace(".", DECIMAL)


def format_minor(
    *,
    amount_minor: int | None,
    currency: str,
    places: int | None = None,
    keep_cents: bool = False,
) -> str:
    return str(
        format_minor_parts(
            amount_minor=amount_minor,
            currency=currency,
            places=places,
            keep_cents=keep_cents,
        )
    )


def format_minor_parts(
    *,
    amount_minor: int | None,
    currency: str,
    places: int | None = None,
    keep_cents: bool = False,
) -> MoneyParts:
    if amount_minor is None:
        return MoneyParts(amount="", currency="")
    if places is None:
        places = decimal_places(currency)
    value = Decimal(amount_minor) / (10**places)
    if places and not keep_cents and amount_minor % (10**places) == 0:
        places = 0
    formatted = number_format(value, decimal_pos=places)
    sign = CURRENCY_SIGNS.get(currency)
    if sign:
        return MoneyParts(amount=formatted, currency=sign, sign_first=True)
    return MoneyParts(amount=formatted, currency=currency)
