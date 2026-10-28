"""The landing page and the billing screens say which currency to show prices in."""

import pytest
from fastapi.testclient import TestClient

from app.modules.billing.selectors import display
from tests.pg.conftest import sign_up


@pytest.fixture(autouse=True)
def bank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        display, "_fetch", lambda: {"rate": "12000", "date": "28.10.2026"}
    )


def test_abroad_the_pages_say_dollars_and_at_home_som(client: TestClient) -> None:
    abroad = {"CF-IPCountry": "KZ"}
    home = client.get("/api/v1/public/home", headers=abroad)
    assert home.status_code == 200, home.text
    assert home.json()["display"] == {
        "country": "KZ",
        "currency": "USD",
        "uzs_per_usd": "12000",
        "rate_date": "28.10.2026",
    }
    here = client.get("/api/v1/public/home", headers={"CF-IPCountry": "UZ"})
    assert here.json()["display"]["currency"] == "UZS"

    auth = sign_up(client)
    plans = client.get("/api/v1/billing", headers=auth | abroad)
    assert plans.status_code == 200, plans.text
    assert plans.json()["display"]["currency"] == "USD"
    paywall = client.get("/api/v1/billing/paywall", headers=auth | abroad)
    assert paywall.json()["display"]["currency"] == "USD"
    assert (
        client.get("/api/v1/billing", headers=auth).json()["display"]["currency"]
        == "UZS"
    )
