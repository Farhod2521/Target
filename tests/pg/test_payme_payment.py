"""Buying a plan through Payme, end to end against PostgreSQL."""

import base64
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from paykit import registry
from paykit.payme import PaymeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.modules.billing.models import Invoice, PaymentTransaction, Plan, Subscription
from tests.pg.conftest import sign_up

MERCHANT = "5e730e8e0b852a417aa49ceb"
KEY = "test-key"
AUTH = {"Authorization": "Basic " + base64.b64encode(f"Paycom:{KEY}".encode()).decode()}


@pytest.fixture
def payme(
    pg_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Payme registered for the length of one test. Its checkout is offline."""
    # The callback route opens its own session rather than taking ``get_db``.
    monkeypatch.setattr("app.common.db.SessionLocal", pg_factory)
    registry.clear()
    registry.register(
        "payme",
        PaymeAdapter(
            merchant_id=MERCHANT,
            key=KEY,
            account_field="order_id",
            checkout_url="https://checkout.test.paycom.uz",
        ),
    )
    yield
    registry.clear()


def _call(
    client: TestClient,
    method: str,
    params: dict[str, Any],
    headers: dict[str, str] = AUTH,
) -> dict[str, Any]:
    answer = client.post(
        "/webhooks/pay/payme",
        json={"jsonrpc": "2.0", "id": 7, "method": method, "params": params},
        headers=headers,
    )
    assert answer.status_code == 200, answer.text
    body: dict[str, Any] = answer.json()
    return body


def _code(client: TestClient, method: str, params: dict[str, Any]) -> int:
    code: int = _call(client, method, params)["error"]["code"]
    return code


def test_a_plan_bought_through_payme(
    client: TestClient, db: Session, payme: None
) -> None:
    auth = sign_up(client)
    db.add(
        Plan(
            code="pro",
            name="Pro",
            tagline="",
            features="",
            price=490000,
            currency="UZS",
            period_days=30,
            max_adsets=10,
            daily_chat_requests=20,
            llm_cost_limit_minor=1000,
            included_pages=1,
            included_google_accounts=0,
            extra_page_price=0,
            is_one_time=False,
            is_active=True,
            sort_order=1,
        )
    )
    db.commit()

    listed = client.get("/api/v1/billing?plan=pro", headers=auth).json()
    assert {"name": "payme", "label": "Payme (Uzcard, Humo)"} in listed["providers"]

    started = client.post(
        "/api/v1/billing/checkout",
        json={"plan": "pro", "provider": "payme"},
        headers=auth,
    )
    assert started.status_code == 200, started.text
    assert started.json()["kind"] == "redirect"
    invoice = db.scalar(select(Invoice))
    assert invoice is not None
    url = started.json()["url"]
    assert url.startswith("https://checkout.test.paycom.uz/")
    link = base64.b64decode(url.rsplit("/", 1)[1]).decode()
    assert f"m={MERCHANT}" in link
    assert f"ac.order_id={invoice.number}" in link
    assert f"a={invoice.amount_minor}" in link
    assert f"/app/billing/invoice/{invoice.number}" in link

    account = {"order_id": invoice.number}
    amount = invoice.amount_minor

    check = {"amount": amount, "account": account}
    stranger = {"Authorization": "Basic " + base64.b64encode(b"Paycom:x").decode()}
    wrong_key = _call(client, "CheckPerformTransaction", check, headers=stranger)
    assert wrong_key["error"]["code"] == -32504
    short = check | {"amount": amount - 100}
    assert _code(client, "CheckPerformTransaction", short) == -31001
    unknown = check | {"account": {"order_id": "0"}}
    assert _code(client, "CheckPerformTransaction", unknown) == -31050
    allowed = _call(client, "CheckPerformTransaction", check)["result"]
    assert allowed == {"allow": True}

    hold = check | {"id": "pm-1", "time": 1_761_660_000_000}
    created = _call(client, "CreateTransaction", hold)["result"]
    assert created["state"] == 1
    again = _call(client, "CreateTransaction", hold)["result"]
    assert again["transaction"] == created["transaction"]
    assert _code(client, "CreateTransaction", hold | {"id": "pm-2"}) == -31008

    performed = _call(client, "PerformTransaction", {"id": "pm-1"})["result"]
    assert performed["state"] == 2 and performed["perform_time"] > 0
    assert _call(client, "PerformTransaction", {"id": "pm-1"})["result"] == performed
    checked = _call(client, "CheckTransaction", {"id": "pm-1"})["result"]
    assert checked["state"] == 2 and checked["transaction"] == created["transaction"]

    db.expire_all()
    invoice = db.get(Invoice, invoice.id)
    assert invoice is not None and invoice.status == "paid"
    attempts = list(db.scalars(select(PaymentTransaction)))
    assert len(attempts) == 1 and attempts[0].external_id == "pm-1"
    subscription = db.scalar(select(Subscription))
    assert subscription is not None and subscription.plan.code == "pro"

    waiting = client.get(f"/api/v1/billing/invoice/{invoice.number}", headers=auth)
    assert waiting.json()["paid"] is True

    window = {"from": 0, "to": 4_102_444_800_000}
    statement = _call(client, "GetStatement", window)["result"]["transactions"]
    assert [row["id"] for row in statement] == ["pm-1"]
    assert statement[0]["account"] == account

    refund = {"id": "pm-1", "reason": 5}
    refunded = _call(client, "CancelTransaction", refund)["result"]
    assert refunded["state"] == -2
    db.expire_all()
    invoice = db.get(Invoice, invoice.id)
    assert invoice is not None and invoice.status == "refunded"
