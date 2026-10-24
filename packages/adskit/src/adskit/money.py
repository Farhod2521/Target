"""What an integer count of minor units means."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Final

from adskit.refs import MinorUnits

ZERO_DECIMAL_CURRENCIES: Final[frozenset[str]] = frozenset(
    {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "JPY",
        "KMF",
        "KRW",
        "MGA",
        "PYG",
        "RWF",
        "UGX",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }
)

DEFAULT_PLACES: Final = 2


def decimal_places(currency: str) -> int:
    """How many digits this currency carries after the separator."""
    return 0 if currency.upper() in ZERO_DECIMAL_CURRENCIES else DEFAULT_PLACES


def to_minor(*, amount: Decimal | str, currency: str) -> MinorUnits:
    """``"12.34"``, ``"USD"`` becomes ``1234``."""
    return MinorUnits(
        int(
            Decimal(str(amount))
            .scaleb(decimal_places(currency))
            .quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    )


@dataclass(frozen=True, slots=True)
class MoneyRules:
    """How one provider counts the smallest unit of a currency."""

    overrides: Mapping[str, int] = MappingProxyType({})

    def decimal_places(self, currency: str) -> int:
        """How many digits this provider carries after the separator."""
        found = self.overrides.get(currency.upper())
        return decimal_places(currency) if found is None else found

    def to_minor(self, *, amount: Decimal | str, currency: str) -> MinorUnits:
        """``"12.34"``, ``"USD"`` becomes ``1234`` - by this provider's count."""
        return MinorUnits(
            int(
                Decimal(str(amount))
                .scaleb(self.decimal_places(currency))
                .quantize(Decimal(1), rounding=ROUND_HALF_UP)
            )
        )


ISO_MONEY: Final = MoneyRules()
