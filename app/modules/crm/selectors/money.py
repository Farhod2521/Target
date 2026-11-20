"""Sales read in one currency.

A pair may change the currency it writes sales in, and a closed sale keeps
the one it was written in. So a sum of sales is never a plain sum of the
column: each amount is read in the wanted currency at the rate of the day
it was closed. An amount the rates cannot price (a day before the first
rate we hold) is left out of the sum and counted, never added as it stands.
"""

from collections.abc import Hashable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.dates import localtime
from app.modules.crm.constants import CURRENCY_LABELS
from core.metrics.exchange import Rates


@dataclass(slots=True)
class Sold:
    minor: int = 0
    # Sales left out of ``minor`` because no rate prices them.
    unpriced: int = 0


class Pricer:
    """Reads amounts in ``target``. The rates are read from the database
    only when the first amount of another currency turns up - until a pair
    changes its currency, never."""

    def __init__(self, db: Session, *, target: str) -> None:
        self._db = db
        self.target = target.upper()
        self._rates: Rates | None = None

    def read(
        self, *, amount_minor: int, currency: str, at: datetime | date | None
    ) -> int | None:
        currency = (currency or self.target).upper()
        if currency == self.target:
            return amount_minor
        if at is None:
            return None
        if self._rates is None:
            from app.modules.metrics.services.rates import rates_for

            self._rates = rates_for(
                self._db, currencies={*CURRENCY_LABELS, self.target, currency}
            )
        day = localtime(at).date() if isinstance(at, datetime) else at
        return self._rates.convert(
            amount_minor=amount_minor, source=currency, target=self.target, day=day
        )

    def add(
        self,
        sold: Sold,
        *,
        amount_minor: int,
        currency: str,
        at: datetime | date | None,
    ) -> None:
        value = self.read(amount_minor=amount_minor, currency=currency, at=at)
        if value is None:
            sold.unpriced += 1
        else:
            sold.minor += value


def sold(
    db: Session, inner: Any, *, target: str, key: Any = None
) -> dict[Hashable, Sold]:
    """The sales among ``inner``'s cards (a subquery of ``crm_cards``), read
    in ``target`` and summed by ``key`` - one of its columns, or everything
    under ``None``."""
    day = func.date(func.timezone(settings.office_timezone, inner.c.closed_at))
    columns = [inner.c.currency, day, func.sum(inner.c.won_amount_minor), func.count()]
    query = select(*([key] if key is not None else []), *columns).where(
        inner.c.won_amount_minor.is_not(None)
    )
    query = query.group_by(*([key] if key is not None else []), inner.c.currency, day)
    pricer = Pricer(db, target=target)
    found: dict[Hashable, Sold] = {}
    for row in db.execute(query):
        *head, currency, closed, amount, cards = row
        total = found.setdefault(head[0] if head else None, Sold())
        value = pricer.read(amount_minor=int(amount), currency=currency, at=closed)
        if value is None:
            total.unpriced += int(cards)
        else:
            total.minor += value
    return found
