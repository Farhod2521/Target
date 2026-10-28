"""Prices in so'm at home and in dollars abroad: the country, the rate, the route."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.common import geo
from app.common.cache import cache
from app.modules.billing.selectors import display


class FakeReader:
    def __init__(self, table: dict[str, str]) -> None:
        self.table = table

    def get(self, address: str) -> dict[str, Any] | None:
        code = self.table.get(address)
        return {"country": {"iso_code": code}} if code else None


@pytest.fixture
def bank(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The Central Bank, answering 12 000 so'm a dollar; counts the calls."""
    calls: list[int] = []

    def fetch() -> dict[str, str] | None:
        calls.append(1)
        return {"rate": "12000.50", "date": "28.10.2026"}

    monkeypatch.setattr(display, "_fetch", fetch)
    return calls


def test_cloudflare_says_first() -> None:
    assert geo.country_of(headers={"CF-IPCountry": "de"}, address="8.8.8.8") == "DE"


def test_the_database_places_a_public_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geo, "_reader", lambda: FakeReader({"84.54.64.1": "UZ"}))
    assert geo.country_of(headers={"CF-IPCountry": "XX"}, address="84.54.64.1") == "UZ"
    assert geo.lookup("5.5.5.5") == ""


def test_private_and_broken_addresses_are_nowhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(geo, "_reader", lambda: FakeReader({"10.0.0.1": "US"}))
    assert geo.lookup("10.0.0.1") == ""
    assert geo.lookup("127.0.0.1") == ""
    assert geo.lookup("testclient") == ""


def test_no_database_yet_means_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(geo.settings, "geoip_db_path", str(tmp_path / "none.mmdb"))
    assert geo.lookup("8.8.8.8") == ""


def test_the_database_is_fetched_for_this_month_then_the_last() -> None:
    months = list(geo._months(datetime(2026, 1, 3, 9, tzinfo=UTC)))
    assert months == [
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2025, 12, 1, tzinfo=UTC),
    ]


def test_a_database_as_new_as_the_month_is_not_fetched_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        geo, "_built_at", lambda path: datetime(2026, 10, 2, tzinfo=UTC)
    )

    def never(url: str, *, into: Path) -> Path:
        raise AssertionError("downloaded again")

    monkeypatch.setattr(geo, "_download", never)
    assert geo.refresh_country_db(now=datetime(2026, 10, 28, tzinfo=UTC)) is False


def test_a_download_that_cannot_place_addresses_is_thrown_away(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "country.mmdb"
    monkeypatch.setattr(geo.settings, "geoip_db_path", str(target))
    junk = tmp_path / "x.part"
    junk.write_bytes(b"not a database")
    monkeypatch.setattr(geo, "_download", lambda url, *, into: junk)
    assert geo.refresh_country_db(now=datetime(2026, 10, 28, tzinfo=UTC)) is False
    assert not junk.exists() and not target.exists()


def test_uzbekistan_and_the_unknown_see_som(bank: list[int]) -> None:
    assert display.display_for(country="UZ").currency == "UZS"
    assert display.display_for(country="").currency == "UZS"
    assert bank == []


def test_abroad_sees_dollars_at_the_cached_rate(bank: list[int]) -> None:
    shown = display.display_for(country="kz")
    assert shown.currency == "USD" and shown.country == "KZ"
    assert shown.uzs_per_usd == Decimal("12000.50") and shown.rate_date == "28.10.2026"
    display.display_for(country="DE")
    assert len(bank) == 1


def test_without_a_rate_everyone_sees_som_and_the_bank_is_not_asked_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(display, "_fetch", lambda: calls.append(1))
    assert display.display_for(country="DE").currency == "UZS"
    assert display.display_for(country="DE").currency == "UZS"
    assert len(calls) == 1


def test_an_outage_falls_back_to_the_last_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.set(display.LAST_RATE_KEY, {"rate": "11900", "date": "27.10.2026"})
    monkeypatch.setattr(display, "_fetch", lambda: None)
    shown = display.display_for(country="DE")
    assert shown.currency == "USD" and shown.uzs_per_usd == Decimal("11900")


def test_a_nonsense_rate_is_no_rate() -> None:
    assert display._read({"rate": "0"}) is None
    assert display._read({"rate": "abc"}) is None
    assert display._read({"rate": "NaN"}) is None


def test_the_route_needs_no_sign_in(client: TestClient, bank: list[int]) -> None:
    abroad = client.get("/api/v1/billing/display", headers={"CF-IPCountry": "DE"})
    assert abroad.status_code == 200
    assert abroad.json() == {
        "country": "DE",
        "currency": "USD",
        "uzs_per_usd": "12000.50",
        "rate_date": "28.10.2026",
    }
    home = client.get("/api/v1/billing/display", headers={"CF-IPCountry": "UZ"})
    assert home.json()["currency"] == "UZS" and home.json()["uzs_per_usd"] is None


def test_when_the_bank_times_out_a_mirror_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get(url: str) -> Any:
        if url == display.CBU_URL:
            raise httpx.ConnectTimeout("timed out")
        return {"time_last_update_unix": 1793145751, "rates": {"UZS": 11940.03}}

    monkeypatch.setattr(display, "_get", get)
    shown = display.display_for(country="DE")
    assert shown.currency == "USD"
    assert shown.uzs_per_usd == Decimal("11940.03")
    assert shown.rate_date == "28.10.2026"


def test_with_every_source_down_the_rate_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(url: str) -> Any:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(display, "_get", down)
    monkeypatch.setattr(display.settings, "usd_uzs_rate", "12000")
    shown = display.display_for(country="DE")
    assert shown.currency == "USD" and shown.uzs_per_usd == Decimal("12000")
