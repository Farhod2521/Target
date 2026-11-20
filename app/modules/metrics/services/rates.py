"""The Central Bank's daily rates, kept so that money of two currencies can
be set against each other for any past day.

``store_rates`` asks the bank for each day we do not hold yet, oldest first,
and keeps every currency it answers. It stops at the first day the bank
does not answer and leaves the rest to the next run, so a day is never
skipped. The bank takes about three seconds a day (measured 2026-11-20), so
the task on the clock reads a few days a run and the past year is read
once, by ``python -m app.modules.metrics.rates``. ``rates_for`` hands the kept rates to the arithmetic in
``core.metrics.exchange``.
"""

import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import httpx
from sqlalchemy import func, select
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
# What one run on the clock may read: enough to make up a week of silence,
# short enough not to hold a worker's slot.
DAYS_PER_RUN: Final = 10

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
    db: Session, *, now: datetime, fetch: Fetch = fetch_day, limit: int | None = None
) -> int:
    """Read the days not held yet, oldest first, up to today - at most
    ``limit`` of them; how many rates were added."""
    today = localtime(now).date()
    floor = today - timedelta(days=HISTORY_DAYS)
    last = db.scalar(select(func.max(FxRate.day)))
    day = max(last + timedelta(days=1), floor) if last else floor
    if limit is not None:
        today = min(today, day + timedelta(days=limit - 1))
    added = 0
    while day <= today:
        try:
            rows = fetch(day)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "metrics.rates_unavailable",
                extra={"day": day.isoformat(), "error": f"{type(exc).__name__}: {exc}"},
            )
            break
        if not rows:
            logger.warning("metrics.rates_empty", extra={"day": day.isoformat()})
            break
        # The bank answers a day off with the last rate it set, under that
        # earlier date: a row we already hold is not written twice.
        fresh = [{"day": d, "currency": c, "rate": r} for d, c, r in rows if d <= day]
        if fresh:
            written = db.execute(
                insert(FxRate)
                .values(fresh)
                .on_conflict_do_nothing()
                .returning(FxRate.day)
            )
            added += len(written.all())
        db.commit()
        day += timedelta(days=1)
    return added


def rates_for(db: Session, *, currencies: Iterable[str]) -> Rates:
    """Every kept rate of these currencies; so'm itself needs none."""
    wanted = {c.upper() for c in currencies if c} - {HOME}
    if not wanted:
        return Rates([])
    return Rates(
        (currency, day, rate)
        for currency, day, rate in db.execute(
            select(FxRate.currency, FxRate.day, FxRate.rate).where(
                FxRate.currency.in_(wanted)
            )
        )
    )
