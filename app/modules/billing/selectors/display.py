"""How prices are shown: in so'm at home, and in dollars to everyone else.

Plans are priced, charged and paid in so'm whatever the visitor's country.
A visitor from abroad is only shown the dollar figure, at the Central Bank
of Uzbekistan's rate of the day; nothing is ever charged in dollars, and the
bill and the payment page still say so'm. Without a rate - the bank is
unreachable and none was ever fetched - everybody sees so'm.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import httpx

from app.common.cache import cache

logger = logging.getLogger(__name__)

HOME_COUNTRY: Final = "UZ"
HOME_CURRENCY: Final = "UZS"
ABROAD_CURRENCY: Final = "USD"

RATE_URL: Final = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/"
RATE_KEY: Final = "billing:usd-rate"
# Outlives every outage: the rate shown when the bank cannot be reached.
LAST_RATE_KEY: Final = "billing:usd-rate:last"
RATE_SECONDS: Final = 6 * 3600
# After a failed fetch, so that every page view does not wait on the bank.
RETRY_SECONDS: Final = 10 * 60
TIMEOUT_SECONDS: Final = 5.0


@dataclass(frozen=True)
class Display:
    country: str
    currency: str
    uzs_per_usd: Decimal | None = None
    rate_date: str = ""


def display_for(*, country: str) -> Display:
    """So'm for Uzbekistan and for a visitor whose country is unknown."""
    country = country.upper()
    if country in ("", HOME_COUNTRY):
        return Display(country=country, currency=HOME_CURRENCY)
    rate = usd_rate()
    if rate is None:
        return Display(country=country, currency=HOME_CURRENCY)
    return Display(
        country=country,
        currency=ABROAD_CURRENCY,
        uzs_per_usd=rate[0],
        rate_date=rate[1],
    )


def display_as_dict(display: Display) -> dict[str, Any]:
    return {
        "country": display.country,
        "currency": display.currency,
        "uzs_per_usd": str(display.uzs_per_usd) if display.uzs_per_usd else None,
        "rate_date": display.rate_date,
    }


def usd_rate() -> tuple[Decimal, str] | None:
    """So'm per dollar and the bank's date for it, cached for a few hours."""
    cached = cache.get(RATE_KEY)
    if isinstance(cached, dict):
        return _read(cached)
    fetched = _fetch()
    if fetched is not None:
        cache.set(RATE_KEY, fetched, RATE_SECONDS)
        cache.set(LAST_RATE_KEY, fetched)
        return _read(fetched)
    last = cache.get(LAST_RATE_KEY)
    cache.set(RATE_KEY, last if isinstance(last, dict) else {}, RETRY_SECONDS)
    return _read(last) if isinstance(last, dict) else None


def _fetch() -> dict[str, str] | None:
    try:
        response = httpx.get(RATE_URL, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        rows = response.json()
        row = rows[0] if isinstance(rows, list) and rows else {}
        entry = {"rate": str(row.get("Rate", "")), "date": str(row.get("Date", ""))}
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning("billing.usd_rate_unavailable", extra={"error": str(exc)})
        return None
    if _read(entry) is None:
        logger.warning("billing.usd_rate_unreadable", extra={"entry": entry})
        return None
    return entry


def _read(entry: dict[str, Any]) -> tuple[Decimal, str] | None:
    try:
        rate = Decimal(str(entry.get("rate", "")))
    except InvalidOperation:
        return None
    if not rate.is_finite() or rate <= 0:
        return None
    return rate, str(entry.get("date", ""))
