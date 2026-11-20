"""Money of one currency read in another, at a day's rate.

Advertising is paid in the ad account's currency and a sale is written in
the CRM's, so no figure that sets one against the other (ROAS, the price of
a customer) exists until both stand in one currency. This is the only
place that crosses them.

A rate is how many so'm one unit of a currency cost on a day, as the
Central Bank set it. The bank sets no rate on a day off, so a day reads the
newest rate on or before it. A day before the first rate we hold has no
answer: ``None``, never a guess - the caller says the amount is unpriced.
"""

from bisect import bisect_right
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Final

from adskit.money import decimal_places, to_minor

# The currency every rate is quoted in; one so'm is one so'm on any day.
HOME: Final = "UZS"


class Rates:
    def __init__(self, rows: Iterable[tuple[str, date, Decimal]]) -> None:
        by_currency: dict[str, list[tuple[date, Decimal]]] = {}
        for currency, day, rate in rows:
            by_currency.setdefault(currency.upper(), []).append((day, rate))
        self._days: dict[str, list[date]] = {}
        self._rates: dict[str, list[Decimal]] = {}
        for currency, found in by_currency.items():
            found.sort()
            self._days[currency] = [day for day, _ in found]
            self._rates[currency] = [rate for _, rate in found]

    def rate(self, currency: str, day: date) -> Decimal | None:
        """So'm for one unit on the day: the newest rate on or before it."""
        currency = currency.upper()
        if currency == HOME:
            return Decimal(1)
        days = self._days.get(currency)
        if not days:
            return None
        at = bisect_right(days, day)
        return self._rates[currency][at - 1] if at else None

    def convert(
        self, *, amount_minor: int, source: str, target: str, day: date
    ) -> int | None:
        """The amount in the target currency's minor units, or ``None`` when
        either currency has no rate for the day."""
        source, target = source.upper(), target.upper()
        if source == target:
            return amount_minor
        paid, wanted = self.rate(source, day), self.rate(target, day)
        if not paid or not wanted:
            return None
        whole = Decimal(amount_minor).scaleb(-decimal_places(source))
        return int(to_minor(amount=whole * paid / wanted, currency=target))
