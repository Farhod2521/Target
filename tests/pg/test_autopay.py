"""Rahmat autopay end to end: a card bound, a plan renewed from it."""

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from paykit import registry
from paykit.multicard import MulticardAdapter, MulticardClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.common.config import settings
from app.common.crypto import decrypt
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.autopay import services
from app.modules.autopay.models import SavedCard
from app.modules.billing.models import Invoice, Plan, Subscription
from tests.pg.conftest import sign_up

STORE = "6"
SECRET = "shop-secret"
TOKEN = "6225f3c93f7a880142782fa4"
SESSION = "67f8dd24e9800"
CARD = {
    "payer_id": SESSION,
    "card_pan": "986027******1519",
    "card_token": TOKEN,
    "phone": "998901234567",
    "holder_name": "ALI VALIYEV",
    "ps": "humo",
    "status": "active",
}


class FakeMulticard:
    """Multicard, with a confirmation that sends the signed payment callback."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.seen: list[str] = []
        self.confirm: dict[str, Any] = {"status": "success"}
        self.otp_hash: str | None = None
        self.callbacks: list[httpx.Response] = []
        self.payments: dict[str, dict[str, Any]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth":
            return _ok(None, token="t", expiry="2099-01-01 00:00:00")
        self.seen.append(f"{request.method} {path}")
        if (request.method, path) == ("POST", "/payment/card/bind"):
            return _ok({"session_id": SESSION, "form_url": f"https://mc/card/{SESSION}"})
        if (request.method, path) == ("GET", f"/payment/card/bind/{SESSION}"):
            return _ok(CARD)
        if (request.method, path) == ("DELETE", f"/payment/card/{TOKEN}"):
            return _ok([])
        if (request.method, path) == ("POST", "/payment"):
            body = json.loads(request.content)
            uuid = f"p{len(self.payments) + 1}"
            self.payments[uuid] = body
            return _ok({"uuid": uuid, "status": "draft", "otp_hash": self.otp_hash})
        if request.method == "PUT" and path.startswith("/payment/"):
            uuid = path.rsplit("/", 1)[1]
            if self.confirm.get("status") == "success":
                self.callbacks.append(self._settle(uuid))
            if "error" in self.confirm:
                return httpx.Response(
                    400, json={"success": False, "error": self.confirm["error"]}
                )
            return _ok({"uuid": uuid, **self.confirm})
        return httpx.Response(404, json={"success": False, "error": {}})

    def _settle(self, uuid: str) -> httpx.Response:
        sent = self.payments[uuid]
        body = {
            "store_id": int(STORE),
            "amount": sent["amount"],
            "invoice_id": sent["invoice_id"],
            "payment_time": "2026-11-03 10:00:00",
            "card_pan": CARD["card_pan"],
            "card_token": TOKEN,
            "uuid": uuid,
        }
        body["sign"] = hashlib.md5(
            f"{STORE}{body['invoice_id']}{body['amount']}{SECRET}".encode()
        ).hexdigest()
        return self.client.post("/webhooks/pay/multicard", json=body)


def _ok(data: Any, **top: Any) -> httpx.Response:
    if data is None:
        return httpx.Response(200, json=top)
    return httpx.Response(200, json={"success": True, "data": data})


@pytest.fixture
def multicard(
    client: TestClient,
    pg_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[FakeMulticard]:
    monkeypatch.setattr("app.common.db.SessionLocal", pg_factory)
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "multicard_autopay_enabled", True)
    monkeypatch.setattr(
        settings,
        "multicard_card_callback_url",
        "https://api.example.uz/webhooks/cards/multicard",
    )
    fake = FakeMulticard(client)
    registry.clear()
    registry.register(
        "multicard",
        MulticardAdapter(
            client=MulticardClient(
                base_url="https://dev-mesh.multicard.uz",
                application_id="app",
                secret=SECRET,
                transport=httpx.MockTransport(fake),
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
    yield fake
    registry.clear()


def _bound(client: TestClient, auth: dict[str, str]) -> dict[str, Any]:
    opened = client.post(
        "/api/v1/billing/card/bind",
        json={"consent": True, "phone": "+998 90 123 45 67"},
        headers=auth,
    )
    assert opened.status_code == 200, opened.text
    reported = client.post("/webhooks/cards/multicard", json={"payer_id": SESSION})
    assert reported.status_code == 200, reported.text
    shown: dict[str, Any] = client.get("/api/v1/billing/card", headers=auth).json()
    return shown


def _plan_running_out(db: Session, *, hours: int = 12) -> Subscription:
    # The one who bound the card: the only account here.
    owner = db.scalar(select(User))
    assert owner is not None
    plan = Plan(
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
    db.add(plan)
    db.flush()
    now = utcnow()
    subscription = Subscription(
        owner_id=owner.id,
        plan_id=plan.id,
        status="active",
        started_at=now - timedelta(days=30),
        term_started_at=now - timedelta(days=30),
        expires_at=now + timedelta(hours=hours),
    )
    db.add(subscription)
    db.commit()
    return subscription


def test_a_card_is_bound_from_multicard_s_word_not_its_callback(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)

    shown = _bound(client, auth)

    assert shown["available"] is True
    assert shown["card"]["pan"] == "986027******1519"
    assert shown["autopay"] is True
    bind = next(r for r in multicard.seen if r == "POST /payment/card/bind")
    assert bind
    # The unsigned callback only said when to ask; the card was read back.
    assert f"GET /payment/card/bind/{SESSION}" in multicard.seen
    card = db.scalar(select(SavedCard))
    assert card is not None and card.token_encrypted is not None
    assert decrypt(card.token_encrypted) == TOKEN
    assert TOKEN.encode() not in card.token_encrypted


def test_no_card_without_consent(
    client: TestClient, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)

    answer = client.post(
        "/api/v1/billing/card/bind",
        json={"consent": False, "phone": "998901234567"},
        headers=auth,
    )

    assert answer.status_code == 400
    assert answer.json()["code"] == "autopay_consent_required"
    assert multicard.seen == []


def test_a_running_out_plan_is_renewed_from_the_card(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    subscription = _plan_running_out(db)
    was = subscription.expires_at

    tried = services.charge_due(db, now=utcnow())

    assert tried == 1
    assert multicard.callbacks[0].json()["success"] is True
    db.expire_all()
    renewed = db.get(Subscription, subscription.id)
    assert renewed is not None and renewed.expires_at == was + timedelta(days=30)
    invoice = db.scalar(select(Invoice))
    assert invoice is not None and invoice.status == "paid"
    sent = next(iter(multicard.payments.values()))
    assert sent["card"] == {"token": TOKEN}
    assert sent["invoice_id"] == invoice.number
    # Renewed: nothing is due, so the next run asks nothing.
    assert services.charge_due(db, now=utcnow()) == 0


def test_a_decline_is_tried_again_a_day_later_not_sooner(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db, hours=20)
    multicard.confirm = {"error": {"code": "ERROR_INSUFFICIENT_FUNDS"}}
    now = utcnow()

    first = services.charge_due(db, now=now)
    soon = services.charge_due(db, now=now + timedelta(hours=2))
    later = services.charge_due(db, now=now + timedelta(hours=24))

    assert (first, soon, later) == (1, 0, 1)
    shown = client.get("/api/v1/billing/card", headers=auth).json()
    assert shown["last_charge"]["outcome"] == "declined"
    assert shown["last_charge"]["error"] == "Kartada mablag' yetarli emas."


def test_a_shop_that_needs_a_code_stops_for_the_term(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    now = utcnow()

    assert services.charge_due(db, now=now) == 1
    assert services.charge_due(db, now=now + timedelta(hours=24)) == 0
    assert not any(r.startswith("PUT ") for r in multicard.seen)
    shown = client.get("/api/v1/billing/card", headers=auth).json()
    assert shown["last_charge"]["outcome"] == "needs_code"


def test_autopay_off_or_card_removed_charges_nothing(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)

    off = client.post(
        "/api/v1/billing/card/autopay", json={"enabled": False}, headers=auth
    )
    paused = services.charge_due(db, now=utcnow())
    removed = client.delete("/api/v1/billing/card", headers=auth)

    assert off.json()["autopay"] is False
    assert paused == 0
    assert removed.json()["card"] is None
    assert f"DELETE /payment/card/{TOKEN}" in multicard.seen
    card = db.scalar(select(SavedCard))
    assert card is not None and card.token_encrypted is None
