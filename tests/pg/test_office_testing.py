"""Office «Testing»: the superuser's real trial payment, and its return."""

import hashlib
import json
from collections.abc import Iterator
from decimal import Decimal
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
from app.modules.accounts.models import User
from app.modules.autopay.models import SavedCard
from app.modules.billing.models import Invoice, Subscription, TestPayment
from tests.pg.conftest import sign_up
from tests.pg.test_autopay import (
    SECRET,
    SESSION,
    STORE,
    TOKEN,
    FakeMulticard,
    _bound,
    _ok,
)

RATE = (Decimal("12650.37"), "25.11.2026")


class FakeShop(FakeMulticard):
    """Multicard, with its checkout page too."""

    def __init__(self, client: TestClient) -> None:
        super().__init__(client)
        self.invoices: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if (request.method, request.url.path) == ("POST", "/payment/invoice"):
            self.invoices.append(json.loads(request.content))
            return _ok({"uuid": "inv1", "checkout_url": "https://checkout.mc/inv1"})
        return super().__call__(request)


@pytest.fixture
def shop(
    client: TestClient,
    pg_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[FakeShop]:
    monkeypatch.setattr("app.common.db.SessionLocal", pg_factory)
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "multicard_autopay_enabled", True)
    monkeypatch.setattr(settings, "billing_currency", "UZS")
    monkeypatch.setattr(
        settings,
        "multicard_card_callback_url",
        "https://api.example.uz/webhooks/cards/multicard",
    )
    monkeypatch.setattr(
        "app.modules.backoffice.services.testing.usd_rate", lambda: RATE
    )
    fake = FakeShop(client)
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


def _superuser(db: Session) -> None:
    user = db.scalar(select(User))
    assert user is not None
    user.is_staff = True
    user.is_superuser = True
    db.commit()


def _callback(
    client: TestClient, *, number: str, tiyin: int, uuid: str
) -> httpx.Response:
    body: dict[str, Any] = {
        "store_id": int(STORE),
        "amount": tiyin,
        "invoice_id": number,
        "payment_time": "2026-11-25 10:00:00",
        "card_pan": "411111******0648",
        "ps": "visa",
        "uuid": uuid,
    }
    body["sign"] = hashlib.md5(f"{STORE}{number}{tiyin}{SECRET}".encode()).hexdigest()
    return client.post("/webhooks/pay/multicard", json=body)


def test_a_dollar_from_the_saved_card_is_paid_and_returned(
    client: TestClient, db: Session, shop: FakeShop
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _superuser(db)

    made = client.post(
        "/api/v1/office/testing/payments",
        json={"method": "card", "usd": "1"},
        headers=auth,
    )

    assert made.status_code == 200, made.text
    row = made.json()
    # A dollar at 12 650,37 is 12 651 so'm, rounded up; Multicard counts tiyin.
    assert row["amount_uzs"] == 12651
    assert shop.payments["p1"]["amount"] == 1265100
    assert shop.payments["p1"]["invoice_id"].startswith("TEST-")
    # The callback was answered «success», so Multicard keeps the money.
    assert shop.callbacks[-1].json()["success"] is True
    assert row["status"] == "paid"
    assert row["can_refund"] is True
    # Nothing was bought.
    assert db.scalar(select(Invoice)) is None
    assert db.scalar(select(Subscription)) is None

    back = client.post(
        f"/api/v1/office/testing/payments/{row['id']}/refund", headers=auth
    )

    assert back.status_code == 200, back.text
    assert back.json()["status"] == "refunded"
    assert shop.dropped == ["p1"]
    listed = client.get("/api/v1/office/testing", headers=auth).json()
    assert listed["rate"] == {"uzs_per_usd": "12650.37", "date": "25.11.2026"}
    assert [r["status"] for r in listed["rows"]] == ["refunded"]


def test_the_checkout_page_is_settled_by_its_callback(
    client: TestClient, db: Session, shop: FakeShop
) -> None:
    auth = sign_up(client)
    _superuser(db)

    made = client.post(
        "/api/v1/office/testing/payments",
        json={"method": "page", "usd": "0.50"},
        headers=auth,
    ).json()

    assert made["status"] == "waiting"
    assert made["page_url"] == "https://checkout.mc/inv1"
    assert shop.invoices[0]["amount"] == 632600  # 6 325,19 so'm up to 6 326

    wrong = _callback(client, number=made["number"], tiyin=100, uuid="u9")
    assert wrong.json()["success"] is False
    paid = _callback(client, number=made["number"], tiyin=632600, uuid="u9")

    assert paid.json()["success"] is True
    db.expire_all()
    row = db.scalar(select(TestPayment))
    assert row is not None
    assert row.status == "paid"
    assert row.external_id == "u9"
    assert row.card_ps == "visa"


def test_a_test_number_nobody_made_is_refused(
    client: TestClient, shop: FakeShop
) -> None:
    answer = _callback(client, number="TEST-0000000000", tiyin=100, uuid="u1")

    assert answer.json()["success"] is False


def test_no_card_is_said_plainly(
    client: TestClient, db: Session, shop: FakeShop
) -> None:
    auth = sign_up(client)
    _superuser(db)

    answer = client.post(
        "/api/v1/office/testing/payments",
        json={"method": "card", "usd": "1"},
        headers=auth,
    )

    assert answer.status_code == 400
    assert "karta" in answer.json()["detail"].lower() or "karta" in answer.text
    assert db.scalar(select(TestPayment)) is None


def test_only_the_superuser_sees_testing(
    client: TestClient, db: Session, shop: FakeShop
) -> None:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    user.is_staff = True
    db.commit()

    assert client.get("/api/v1/office/testing", headers=auth).status_code == 404
    posted = client.post(
        "/api/v1/office/testing/payments",
        json={"method": "page", "usd": "1"},
        headers=auth,
    )
    assert posted.status_code == 404
    assert shop.invoices == []

    _superuser(db)
    me = client.get("/api/v1/office/me", headers=auth).json()
    assert "testing" in me["sections"]


def test_a_test_card_is_bound_here_and_the_account_card_left_alone(
    client: TestClient, db: Session, shop: FakeShop
) -> None:
    auth = sign_up(client)
    _superuser(db)

    opened = client.post(
        "/api/v1/office/testing/cards",
        json={"phone": "+998 90 123 45 67"},
        headers=auth,
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["form_url"].startswith("https://mc/card/")
    assert shop.binds[-1]["redirect_url"].endswith("/ofis/test/?card=bound")
    # Multicard's callback for the page: no account card has this session.
    reported = client.post("/webhooks/cards/multicard", json={"payer_id": SESSION})
    assert reported.status_code == 200, reported.text

    shown = client.get("/api/v1/office/testing", headers=auth).json()
    assert shown["card"] is None
    assert [c["pan"] for c in shown["test_cards"]] == ["986027******1519"]
    card_id = shown["test_cards"][0]["id"]

    paid = client.post(
        "/api/v1/office/testing/payments",
        json={"method": "card", "usd": "1", "card_id": card_id},
        headers=auth,
    ).json()

    assert paid["status"] == "paid"
    assert paid["card_pan"] == "986027******1519"
    assert shop.payments["p1"]["card"] == {"token": TOKEN}
    assert db.scalar(select(SavedCard)) is None

    gone = client.delete(f"/api/v1/office/testing/cards/{card_id}", headers=auth)
    assert gone.status_code == 200, gone.text
    assert f"DELETE /payment/card/{TOKEN}" in shop.seen
    after = client.get("/api/v1/office/testing", headers=auth).json()
    assert after["test_cards"] == []


def test_a_test_card_page_opens_with_no_phone(
    client: TestClient, db: Session, shop: FakeShop
) -> None:
    auth = sign_up(client)
    _superuser(db)

    opened = client.post("/api/v1/office/testing/cards", json={}, headers=auth)

    assert opened.status_code == 200, opened.text
    # Multicard needs a phone for Humo only; the code goes to the card's number.
    assert "phone" not in shop.binds[-1]


def test_a_test_card_phone_given_is_sent(
    client: TestClient, db: Session, shop: FakeShop
) -> None:
    auth = sign_up(client)
    _superuser(db)

    client.post(
        "/api/v1/office/testing/cards", json={"phone": "90 123 45 67"}, headers=auth
    )

    assert shop.binds[-1]["phone"] == "998901234567"
