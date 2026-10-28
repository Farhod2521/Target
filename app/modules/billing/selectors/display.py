"""How prices are shown: in so'm at home, and in dollars to everyone else.

Plans are priced, charged and paid in so'm whatever the visitor's country.
A visitor from abroad is only shown the dollar figure, at the Central Bank
of Uzbekistan's rate of the day; nothing is ever charged in dollars, and the
bill and the payment page still say so'm.

The bank's site does not answer every network - a server abroad times out -
so two public mirrors of the market rate stand behind it, and behind them
``USD_UZS_RATE`` from the environment. With none of these, everybody sees
so'm.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import httpx

from app.common.cache import cache
from app.common.config import settings

logger = logging.getLogger(__name__)

HOME_COUNTRY: Final = "UZ"
HOME_CURRENCY: Final = "UZS"
ABROAD_CURRENCY: Final = "USD"

CBU_URL: Final = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/"
ER_API_URL: Final = "https://open.er-api.com/v6/latest/USD"
JSDELIVR_URL: Final = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
RATE_KEY: Final = "billing:usd-rate"
# Outlives every outage: the rate shown when the bank cannot be reached.
LAST_RATE_KEY: Final = "billing:usd-rate:last"
RATE_SECONDS: Final = 6 * 3600
# After a failed fetch, so that every page view does not wait on the bank.
RETRY_SECONDS: Final = 10 * 60
# Short on connecting: a page view waits for this when the cache is empty.
TIMEOUT: Final = httpx.Timeout(5.0, connect=2.0)


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
    if not isinstance(last, dict):
        last = {"rate": settings.usd_uzs_rate, "date": ""}
    cache.set(RATE_KEY, last, RETRY_SECONDS)
    return _read(last)


def _fetch() -> dict[str, str] | None:
    """The first source that answers with a usable rate."""
    for name, source in SOURCES:
        try:
            entry = source()
        except (httpx.HTTPError, ValueError, LookupError, AttributeError) as exc:
            logger.warning(
                "billing.usd_rate_unavailable",
                extra={"source": name, "error": f"{type(exc).__name__}: {exc}"},
            )
            continue
        if _read(entry) is not None:
            return entry
        logger.warning(
            "billing.usd_rate_unreadable", extra={"source": name, "entry": entry}
        )
    return None


def _cbu() -> dict[str, str]:
    row = _get(CBU_URL)[0]
    return {"rate": str(row["Rate"]), "date": str(row["Date"])}


def _er_api() -> dict[str, str]:
    body = _get(ER_API_URL)
    stamp = datetime.fromtimestamp(int(body["time_last_update_unix"]), UTC)
    return {
        "rate": str(round(Decimal(str(body["rates"]["UZS"])), 2)),
        "date": stamp.strftime("%d.%m.%Y"),
    }


def _jsdelivr() -> dict[str, str]:
    body = _get(JSDELIVR_URL)
    day = datetime.strptime(str(body["date"]), "%Y-%m-%d")
    return {
        "rate": str(round(Decimal(str(body["usd"]["uzs"])), 2)),
        "date": day.strftime("%d.%m.%Y"),
    }


def _get(url: str) -> Any:
    response = httpx.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


SOURCES: Final = (("cbu", _cbu), ("er-api", _er_api), ("jsdelivr", _jsdelivr))


def _read(entry: dict[str, Any]) -> tuple[Decimal, str] | None:
    try:
        rate = Decimal(str(entry.get("rate", "")))
    except InvalidOperation:
        return None
    if not rate.is_finite() or rate <= 0:
        return None
    return rate, str(entry.get("date", ""))
