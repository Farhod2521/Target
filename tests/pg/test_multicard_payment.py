"""Buying a plan through Multicard (Rahmat), end to end against PostgreSQL."""

import hashlib
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from paykit import registry
from paykit.multicard import MulticardAdapter, MulticardClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.modules.billing.models import Invoice, PaymentTransaction, Plan, Subscription
from tests.pg.conftest import sign_up

SECRET = "test-secret"
STORE = "6"


@pytest.fixture
def multicard(
    pg_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[list[dict[str, Any]]]:
    """Multicard, faked at the HTTP edge, registered for the length of one test."""
    # The callback route opens its own session rather than taking ``get_db``.
    monkeypatch.setattr("app.common.db.SessionLocal", pg_factory)
    sent: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return httpx.Response(
                200, json={"token": "t", "expiry": "2099-01-01 00:00:00"}
            )
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "uuid": "inv-uuid",
                    "checkout_url": "https://dev-app.rhmt.uz/invoice/inv-uuid",
                },
            },
        )

    registry.clear()
    registry.register(
        "multicard",
        MulticardAdapter(
            client=MulticardClient(
                base_url="https://dev-mesh.multicard.uz",
                application_id="app",
                secret=SECRET,
                transport=httpx.MockTransport(answer),
            ),
            store_id=STORE,
            secret=SECRET,
            callback_url="https://api.example.uz/webhooks/pay/multicard",
            decimal_places=2,
            ofd_mxik="10305008002000000",
            ofd_package_code="1545643",
            ofd_name="TargetologAI obunasi",
        ),
    )
    yield sent
    registry.clear()


def _signed(**fields: Any) -> dict[str, Any]:
    body = {
        "store_id": int(STORE),
        "billing_id": None,
        "payment_time": "2026-10-28 15:00:00",
        "phone": "998901234567",
        "card_pan": "860053******8829",
        "ps": "uzcard",
        "card_token": "never-kept",
        "receipt_url": "https://ofd.example/r",
    } | fields
    body["sign"] = hashlib.md5(
        f"{body['store_id']}{body['invoice_id']}{body['amount']}{SECRET}".encode()
    ).hexdigest()
    return body


def test_a_plan_bought_through_multicard(
    client: TestClient, db: Session, multicard: list[dict[str, Any]]
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
    assert {"name": "multicard", "label": "Rahmat (Uzcard, Humo, Visa)"} in listed[
        "providers"
    ]

    started = client.post(
        "/api/v1/billing/checkout",
        json={"plan": "pro", "provider": "multicard"},
        headers=auth,
    )
    assert started.status_code == 200, started.text
    assert started.json()["kind"] == "redirect"
    assert started.json()["url"] == "https://dev-app.rhmt.uz/invoice/inv-uuid"
    invoice = db.scalar(select(Invoice))
    assert invoice is not None
    sent = multicard[0]
    assert sent["invoice_id"] == invoice.number
    assert sent["amount"] == invoice.amount_minor
    assert sent["ofd"][0]["name"].startswith("TargetologAI obunasi: Pro")

    forged = _signed(
        invoice_id=invoice.number, amount=invoice.amount_minor, uuid="pay-1"
    )
    forged["sign"] = "0" * 32
    refused = client.post("/webhooks/pay/multicard", json=forged)
    assert refused.status_code == 403 and refused.json()["success"] is False

    short = client.post(
        "/webhooks/pay/multicard",
        json=_signed(
            invoice_id=invoice.number, amount=invoice.amount_minor - 100, uuid="pay-0"
        ),
    )
    assert short.status_code == 200 and short.json()["success"] is False

    paid = _signed(invoice_id=invoice.number, amount=invoice.amount_minor, uuid="pay-1")
    first = client.post("/webhooks/pay/multicard", json=paid)
    assert first.json() == {"success": True, "message": "OK"}
    again = client.post("/webhooks/pay/multicard", json=paid)
    assert again.json() == {"success": True, "message": "OK"}

    db.expire_all()
    invoice = db.get(Invoice, invoice.id)
    assert invoice is not None and invoice.status == "paid"
    attempts = list(db.scalars(select(PaymentTransaction)))
    assert len(attempts) == 1 and attempts[0].external_id == "pay-1"
    assert "card_token" not in attempts[0].raw and "sign" not in attempts[0].raw
    subscription = db.scalar(select(Subscription))
    assert subscription is not None and subscription.plan.code == "pro"

    waiting = client.get(f"/api/v1/billing/invoice/{invoice.number}", headers=auth)
    assert waiting.json()["polling"] is False

    replayed = client.post(
        "/webhooks/pay/multicard",
        json=_signed(
            invoice_id=invoice.number, amount=invoice.amount_minor, uuid="pay-2"
        ),
    )
    assert replayed.json()["success"] is False
