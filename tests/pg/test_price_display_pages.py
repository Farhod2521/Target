"""The landing page and the billing screens say which currency to show prices in."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.billing.models import Plan

from app.modules.billing.selectors import display
from tests.pg.conftest import sign_up


@pytest.fixture(autouse=True)
def bank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        display, "_fetch", lambda: {"rate": "12000", "date": "28.10.2026"}
    )


def test_abroad_the_pages_say_dollars_and_at_home_som(
    client: TestClient, db: Session
) -> None:
    db.add(
        Plan(
            code="standart",
            name="Standart",
            tagline="",
            features="",
            price=490000,
            currency="UZS",
            period_days=30,
            max_adsets=20,
            daily_chat_requests=20,
            llm_cost_limit_minor=1000,
            included_pages=3,
            included_google_accounts=0,
            extra_page_price=249000,
            is_one_time=False,
            is_active=True,
            sort_order=1,
        )
    )
    db.commit()
    abroad = {"CF-IPCountry": "KZ"}
    home = client.get("/api/v1/public/home", headers=abroad)
    assert home.status_code == 200, home.text
    assert home.json()["plans"][0]["shown"] == {
        "currency": "USD",
        "price": 40.83,
        "extra_page_price": 20.75,
        "per_page": 13.58,
        "approximate": True,
    }
    assert home.json()["featured_plan"] is None or home.json()["featured_plan"]["shown"]
    assert home.json()["entry_plan"]["shown"]["price"] == 40.83
    assert home.json()["display"] == {
        "country": "KZ",
        "currency": "USD",
        "uzs_per_usd": "12000",
        "rate_date": "28.10.2026",
    }
    here = client.get("/api/v1/public/home", headers={"CF-IPCountry": "UZ"})
    assert here.json()["display"]["currency"] == "UZS"
    assert here.json()["plans"][0]["shown"] == {
        "currency": "UZS",
        "price": 490000,
        "extra_page_price": 249000,
        "per_page": 163000,
        "approximate": False,
    }

    auth = sign_up(client)
    plans = client.get("/api/v1/billing", headers=auth | abroad)
    assert plans.status_code == 200, plans.text
    assert plans.json()["display"]["currency"] == "USD"
    assert plans.json()["plans"][0]["shown"]["price"] == 40.83
    paywall = client.get("/api/v1/billing/paywall", headers=auth | abroad)
    assert paywall.json()["display"]["currency"] == "USD"
    assert (
        client.get("/api/v1/billing", headers=auth).json()["display"]["currency"]
        == "UZS"
    )
