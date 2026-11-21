"""The Central Bank's daily rates, kept so that money of two currencies can
be set against each other for any past day.

``store_rates`` asks the bank for each day we do not hold yet, the newest
first, and keeps every currency it answers. It stops at the first day the
bank does not answer and leaves the rest to the next run. The bank takes
about three seconds a day (measured 2026-11-20), so the task on the clock
looks only at the last ``RECENT_DAYS`` - one day's read on an ordinary day -
and the past year is read once, by ``python -m app.modules.metrics.rates``.

Newest first matters: a figure is priced only by a rate at most
``core.metrics.exchange.MAX_AGE_DAYS`` old, so until the recent days are
held nothing recent can be priced at all. ``rates_for`` hands the kept rates to the arithmetic in
``core.metrics.exchange``.
"""

import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.modules.metrics.models import FxRate
from core.metrics.exchange import HOME, Rates

logger = logging.getLogger(__name__)

CBU_DAY_URL: Final = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/all/{day}/"
TIMEOUT: Final = httpx.Timeout(10.0, connect=5.0)
# How far back the first run reads: the longest range a report may ask for.
HISTORY_DAYS: Final = 400
# How far back a run on the clock looks: it makes up a week of silence by
# itself, and reads one day when nothing was missed.
RECENT_DAYS: Final = 7

Row = tuple[date, str, Decimal]
Fetch = Callable[[date], list[Row]]


def read_rows(body: Any) -> list[Row]:
    """The bank's answer for one day as (the day the rate was set, currency,
    so'm for one unit). A row that cannot be read is left out."""
    rows: list[Row] = []
    for item in body if isinstance(body, list) else []:
        try:
            day = datetime.strptime(str(item["Date"]), "%d.%m.%Y").date()
            currency = str(item["Ccy"]).upper()
            nominal = Decimal(str(item["Nominal"]))
            rate = Decimal(str(item["Rate"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        if len(currency) != 3 or nominal <= 0 or rate <= 0:
            continue
        rows.append((day, currency, rate / nominal))
    return rows


def fetch_day(day: date) -> list[Row]:
    response = httpx.get(CBU_DAY_URL.format(day=day.isoformat()), timeout=TIMEOUT)
    response.raise_for_status()
    return read_rows(response.json())


def store_rates(
    db: Session,
    *,
    now: datetime,
    fetch: Fetch = fetch_day,
    back: int = HISTORY_DAYS,
) -> int:
    """Read every day of the last ``back`` that is not held yet, the newest
    first, so that today's figures can be priced before last year's; how
    many rates were added.

    A day the bank answers with an earlier date - a day off - is kept under
    its own date too, with the rate that stood on it: every day asked then
    has a row, and none is asked twice. It stops at the first day the bank
    does not answer; the next run goes on from there.
    """
    today = localtime(now).date()
    floor = today - timedelta(days=back)
    held = set(db.scalars(select(FxRate.day).where(FxRate.day >= floor).distinct()))
    added = 0
    for day in (today - timedelta(days=n) for n in range(back + 1)):
        if day in held:
            continue
        try:
            rows = fetch(day)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "metrics.rates_unavailable",
                extra={"day": day.isoformat(), "error": f"{type(exc).__name__}: {exc}"},
            )
            break
        fresh: dict[tuple[date, str], Decimal] = {}
        for set_on, currency, rate in rows:
            if set_on > day:
                continue
            fresh[set_on, currency] = rate
            fresh[day, currency] = rate
        if not fresh:
            logger.warning("metrics.rates_empty", extra={"day": day.isoformat()})
            break
        written = db.execute(
            insert(FxRate)
            .values(
                [
                    {"day": on, "currency": currency, "rate": rate}
                    for (on, currency), rate in fresh.items()
                ]
            )
            .on_conflict_do_nothing()
            .returning(FxRate.day)
        )
        added += len(written.all())
        db.commit()
        held.update(on for on, _ in fresh)
    return added


def rates_rows(
    db: Session, *, currencies: Iterable[str]
) -> list[tuple[str, date, Decimal]]:
    """Every kept rate of these currencies; so'm itself needs none."""
    wanted = {c.upper() for c in currencies if c} - {HOME}
    if not wanted:
        return []
    return [
        (currency, day, rate)
        for currency, day, rate in db.execute(
            select(FxRate.currency, FxRate.day, FxRate.rate).where(
                FxRate.currency.in_(wanted)
            )
        )
    ]


def rates_for(db: Session, *, currencies: Iterable[str]) -> Rates:
    return Rates(rates_rows(db, currencies=currencies))
