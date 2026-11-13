"""A test account pays in Multicard's sandbox; everyone else pays live."""

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

from app.modules.billing.models import Invoice, PaymentTransaction, Plan
from app.modules.billing.services.providers import (
    MULTICARD_TEST,
    TEST_EMAILS,
    sandbox_callback_url,
)
from tests.pg.conftest import sign_up

TESTER = next(iter(TEST_EMAILS))
SHOPS = {"multicard": ("6", "live-secret"), "multicard_test": ("77", "test-secret")}


def _adapter(name: str, sent: list[tuple[str, dict[str, Any]]]) -> MulticardAdapter:
    store, secret = SHOPS[name]

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return httpx.Response(
                200, json={"token": "t", "expiry": "2099-01-01 00:00:00"}
            )
        sent.append((name, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"uuid": "u", "checkout_url": f"https://{name}.example/u"},
            },
        )

    return MulticardAdapter(
        name=name,  # type: ignore[arg-type]
        client=MulticardClient(
            base_url="https://x.example",
            application_id="app",
            secret=secret,
            transport=httpx.MockTransport(answer),
        ),
        store_id=store,
        secret=secret,
        callback_url=f"https://api.example.uz/webhooks/pay/{name}",
        decimal_places=2,
        ofd_mxik="10305008002000000",
        ofd_package_code="1545643",
        ofd_name="TargetologAI obunasi",
    )


@pytest.fixture
def shops(
    pg_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, db: Session
) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    monkeypatch.setattr("app.common.db.SessionLocal", pg_factory)
    sent: list[tuple[str, dict[str, Any]]] = []
    registry.clear()
    for name in SHOPS:
        registry.register(name, _adapter(name, sent))  # type: ignore[arg-type]
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
    yield sent
    registry.clear()


def _pay(client: TestClient, auth: dict[str, str], provider: str) -> httpx.Response:
    return client.post(
        "/api/v1/billing/checkout",
        json={"plan": "pro", "provider": provider},
        headers=auth,
    )


def test_the_sandbox_is_not_offered_as_a_method(
    client: TestClient, shops: list[tuple[str, dict[str, Any]]]
) -> None:
    auth = sign_up(client, email=TESTER)
    names = [
        p["name"]
        for p in client.get("/api/v1/billing?plan=pro", headers=auth).json()[
            "providers"
        ]
    ]
    assert names == ["multicard"]


def test_a_test_account_pays_in_the_sandbox(
    client: TestClient, db: Session, shops: list[tuple[str, dict[str, Any]]]
) -> None:
    auth = sign_up(client, email=TESTER)
    started = _pay(client, auth, "multicard")
    assert started.status_code == 200, started.text
    assert started.json()["url"] == "https://multicard_test.example/u"
    assert [name for name, _ in shops] == ["multicard_test"]

    invoice = db.scalar(select(Invoice))
    assert invoice is not None
    store, secret = SHOPS["multicard_test"]
    body: dict[str, Any] = {
        "store_id": int(store),
        "invoice_id": invoice.number,
        "amount": invoice.amount_minor,
        "uuid": "pay-sandbox",
        "payment_time": "2026-11-13 15:00:00",
    }
    sign = f"{store}{invoice.number}{invoice.amount_minor}"
    body["sign"] = hashlib.md5(f"{sign}{secret}".encode()).hexdigest()

    # The live shop does not take the sandbox's signature.
    assert client.post("/webhooks/pay/multicard", json=body).status_code == 403
    paid = client.post("/webhooks/pay/multicard_test", json=body)
    assert paid.json()["success"] is True, paid.text
    db.expire_all()
    assert invoice.status == "paid"
    row = db.scalar(select(PaymentTransaction))
    assert row is not None
    assert (row.provider, row.external_id) == ("multicard_test", "pay-sandbox")


def test_everyone_else_pays_live_and_cannot_reach_the_sandbox(
    client: TestClient, shops: list[tuple[str, dict[str, Any]]]
) -> None:
    auth = sign_up(client)
    assert _pay(client, auth, "multicard").json()["url"] == (
        "https://multicard.example/u"
    )
    assert [name for name, _ in shops] == ["multicard"]
    refused = _pay(client, auth, MULTICARD_TEST)
    assert refused.status_code != 200
    assert [name for name, _ in shops] == ["multicard"]


def test_the_sandbox_callback_address() -> None:
    assert (
        sandbox_callback_url("https://api.example.uz/webhooks/pay/multicard")
        == "https://api.example.uz/webhooks/pay/multicard_test"
    )
