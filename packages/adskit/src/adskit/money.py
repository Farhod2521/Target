"""What an integer count of minor units means.

``MinorUnits`` is declared in :mod:`adskit.refs` and used by every port, but
the type alone does not say how many of them make one unit of the currency -
and that is the fact that turns ``1000 USD`` into ten dollars and ``1000
JPY`` into a thousand yen.

It lives here, in the contracts package, because both sides need it and
neither may import the other. An adapter reading a provider's answer has to
turn "12.34" into an integer; the Django layer turns that integer back into
something a person reads. Two copies of this table is two chances for one of
them to be missing a currency, and the failure is silent: prices a hundred
times too small, in a currency whose speakers would notice immediately.

No formatting here. Which separator a number is shown with depends on the
reader's language, and this package has no reader.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Final

from adskit.refs import MinorUnits

# Currencies whose smallest unit *is* the unit: there are no sub-units to
# show, and dividing by a hundred would turn ¥1000 into ¥10.
#
# ISO 4217's own list, not a judgement about which currencies matter.
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

# What an unknown currency is assumed to do. Two is right for all but the
# seventeen above, and guessing zero for an unrecognised code would show a
# figure a hundred times too small rather than a rounding error.
DEFAULT_PLACES: Final = 2


def decimal_places(currency: str) -> int:
    """How many digits this currency carries after the separator."""
    return 0 if currency.upper() in ZERO_DECIMAL_CURRENCIES else DEFAULT_PLACES


def to_minor(*, amount: Decimal | str, currency: str) -> MinorUnits:
    """``"12.34"``, ``"USD"`` becomes ``1234``.

    A string is accepted because that is what providers send. Meta answers
    spend as ``"12.34"`` - whole currency, as text - while answering budgets
    as ``"1234"``, minor units, also as text. The two look identical in a
    JSON payload and differ by a factor of a hundred, which is why the
    conversion is named at every call site rather than inferred.

    Rounded half-up rather than truncated. A provider reporting a third of a
    cent is reporting a real amount, and dropping it on every row of a
    ninety-day range loses money that was actually spent.
    """
    return MinorUnits(
        int(
            Decimal(str(amount))
            .scaleb(decimal_places(currency))
            .quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    )


@dataclass(frozen=True, slots=True)
class MoneyRules:
    """How one provider counts the smallest unit of a currency.

    ISO 4217 is the starting point and ``overrides`` is where a provider
    disagrees with it. That disagreement is real and it is not a rounding
    error: a platform that counts a currency in whole units where the
    standard counts hundredths reads a budget a **hundred times** larger
    than the one that was typed, and the campaign spends it.

    The table lives with the adapter that needs it rather than here,
    because it is that provider's arithmetic and not the currency's. This
    package holds the shape and the standard's answer; ``metaads`` holds
    Meta's, and a second provider would hold its own without either of
    them editing the other.

    An empty ``overrides`` is the ordinary case and means "this provider
    counts money the way the standard does" - which is what every
    unverified currency is treated as, deliberately: guessing an offset is
    how the hundredfold error gets written down on purpose.
    """

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


# What a provider that has said nothing is assumed to do. Named rather than
# constructed at each call site so that "nobody told us" reads the same
# everywhere it appears, and so the registry has something to default to.
ISO_MONEY: Final = MoneyRules()
