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
from app.common.crypto import decrypt, encrypt
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
        self.checkout_url: str | None = None
        # The shop may debit without a code: an empty PUT goes through even
        # when POST /payment answered an otp_hash.
        self.debit_without_code = False
        self.code = "50112"
        self.binds: list[dict[str, Any]] = []
        self.confirmed: list[dict[str, Any]] = []
        self.callbacks: list[httpx.Response] = []
        self.payments: dict[str, dict[str, Any]] = {}
        self.dropped: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth":
            return _ok(None, token="t", expiry="2099-01-01 00:00:00")
        self.seen.append(f"{request.method} {path}")
        if (request.method, path) == ("POST", "/payment/card/bind"):
            self.binds.append(json.loads(request.content))
            return _ok(
                {"session_id": SESSION, "form_url": f"https://mc/card/{SESSION}"}
            )
        if (request.method, path) == ("GET", f"/payment/card/bind/{SESSION}"):
            return _ok(CARD)
        if (request.method, path) == ("DELETE", f"/payment/card/{TOKEN}"):
            return _ok([])
        if (request.method, path) == ("POST", "/payment"):
            body = json.loads(request.content)
            uuid = f"p{len(self.payments) + 1}"
            self.payments[uuid] = body
            return _ok(
                {
                    "uuid": uuid,
                    "status": "draft",
                    "otp_hash": self.otp_hash,
                    "checkout_url": self.checkout_url,
                }
            )
        if request.method == "GET" and path.startswith("/payment/p"):
            return _ok({"uuid": path.rsplit("/", 1)[1], "status": "draft"})
        if request.method == "DELETE" and path.startswith("/payment/p"):
            self.dropped.append(path.rsplit("/", 1)[1])
            return _ok({"status": "revert"})
        if request.method == "PUT" and path.startswith("/payment/"):
            uuid = path.rsplit("/", 1)[1]
            sent = json.loads(request.content or b"{}")
            self.confirmed.append(sent)
            if (
                self.otp_hash
                and sent.get("otp") != self.code
                and not (self.debit_without_code and not sent)
            ):
                return httpx.Response(
                    400,
                    json={"success": False, "error": {"code": "ERROR_WRONG_OTP"}},
                )
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


def _plan(
    db: Session,
    *,
    code: str = "pro",
    price: int = 490000,
    days: int = 30,
    one_time: bool = False,
) -> Plan:
    plan = Plan(
        code=code,
        name=code.capitalize(),
        tagline="",
        features="",
        price=price,
        currency="UZS",
        period_days=days,
        max_adsets=10,
        daily_chat_requests=20,
        llm_cost_limit_minor=1000,
        included_pages=1,
        included_google_accounts=0,
        extra_page_price=0,
        is_one_time=one_time,
        is_active=True,
        sort_order=1,
    )
    db.add(plan)
    db.flush()
    return plan


def _plan_running_out(
    db: Session, *, hours: int = 12, plan: Plan | None = None
) -> Subscription:
    # The one who bound the card: the only account here.
    owner = db.scalar(select(User))
    assert owner is not None
    plan = plan or _plan(db)
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


def test_no_card_without_consent(client: TestClient, multicard: FakeMulticard) -> None:
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
    # Only the empty confirmation was tried, and refused.
    assert multicard.confirmed == [{}]
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


def _start_running_out(db: Session) -> Subscription:
    _plan(db, code="standart")
    start = _plan(db, code="start", price=49000, days=7, one_time=True)
    return _plan_running_out(db, plan=start)


def test_start_running_out_is_followed_by_standart_from_the_card(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    subscription = _start_running_out(db)

    shown = client.get("/api/v1/billing/card", headers=auth).json()
    tried = services.charge_due(db, now=utcnow())

    # Start is not sold twice: the card is said to pay for Standart, and does.
    assert shown["renews_as"]["code"] == "standart"
    assert shown["renews_as"]["price_minor"] == 490000 * 100
    assert tried == 1
    db.expire_all()
    renewed = db.get(Subscription, subscription.id)
    assert renewed is not None and renewed.plan.code == "standart"
    assert renewed.expires_at > utcnow() + timedelta(days=29)
    invoice = db.scalar(select(Invoice))
    assert invoice is not None and invoice.status == "paid"
    assert invoice.plan is not None and invoice.plan.code == "standart"
    assert services.charge_due(db, now=utcnow()) == 0


def test_a_stopped_subscription_does_not_move_start_to_standart(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    subscription = _start_running_out(db)

    client.post("/api/v1/billing/card/autopay", json={"enabled": False}, headers=auth)
    shown = client.get("/api/v1/billing/card", headers=auth).json()

    assert shown["renews_as"] is None
    assert services.charge_due(db, now=utcnow()) == 0
    db.expire_all()
    kept = db.get(Subscription, subscription.id)
    assert kept is not None and kept.plan.code == "start"
    assert db.scalar(select(Invoice)) is None


def test_the_start_checkout_says_standart_follows(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _plan(db, code="standart")
    _plan(db, code="start", price=49000, days=7, one_time=True)
    db.commit()

    start = client.get("/api/v1/billing?plan=start", headers=auth)
    pro = client.get("/api/v1/billing?plan=standart", headers=auth)

    assert start.status_code == 200, start.text
    assert start.json()["renews_as"]["code"] == "standart"
    assert pro.json()["renews_as"]["code"] == "standart"


# --- A bill paid from the card by its owner, with no payment page -----------


def _pay(client: TestClient, auth: dict[str, str]) -> httpx.Response:
    answer: httpx.Response = client.post(
        "/api/v1/billing/checkout", json={"plan": "pro", "card": True}, headers=auth
    )
    return answer


def test_a_bill_is_paid_from_the_card_with_no_payment_page(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)

    answer = _pay(client, auth)

    assert answer.status_code == 200, answer.text
    started = answer.json()
    assert started["kind"] == "wait" and started["url"] == ""
    assert "POST /payment/invoice" not in multicard.seen
    assert multicard.confirmed == [{}]
    assert multicard.callbacks[0].json()["success"] is True
    db.expire_all()
    invoice = db.scalar(select(Invoice))
    assert invoice is not None and invoice.status == "paid"
    assert invoice.number == started["number"]
    sent = next(iter(multicard.payments.values()))
    assert sent["card"] == {"token": TOKEN}


def test_a_shop_that_asks_for_a_code_is_paid_once_the_owner_types_it(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"

    started = _pay(client, auth).json()
    assert started["kind"] == "code" and started["charge"]
    assert multicard.confirmed == [{}]
    url = f"/api/v1/billing/invoice/{started['number']}/confirm"

    wrong = client.post(
        url, json={"charge": started["charge"], "code": "00000"}, headers=auth
    )
    assert wrong.status_code == 400 and wrong.json()["code"] == "card_code_wrong"
    db.expire_all()
    assert db.scalar(select(Invoice.status)) == "pending"

    right = client.post(
        url, json={"charge": started["charge"], "code": " 50112 "}, headers=auth
    )
    assert right.status_code == 200, right.text
    assert multicard.confirmed[-1] == {"otp": "50112", "debit_available": False}
    db.expire_all()
    assert db.scalar(select(Invoice.status)) == "paid"


def test_renewal_is_taken_with_an_otp_hash_when_the_shop_needs_no_code(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    multicard.debit_without_code = True

    assert services.charge_due(db, now=utcnow()) == 1

    assert multicard.confirmed == [{}]
    db.expire_all()
    assert db.scalar(select(Invoice.status)) == "paid"
    shown = client.get("/api/v1/billing/card", headers=auth).json()
    assert shown["last_charge"]["outcome"] == "charged"


def test_card_pay_with_an_otp_hash_is_taken_when_the_shop_needs_no_code(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    multicard.debit_without_code = True

    started = _pay(client, auth).json()

    assert started["kind"] == "wait" and started["charge"] == ""
    db.expire_all()
    assert db.scalar(select(Invoice.status)) == "paid"


def test_a_payment_to_confirm_on_multicards_page_sends_the_owner_there(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    multicard.checkout_url = "https://checkout.multicard.uz/payment/p1"

    started = _pay(client, auth).json()

    assert started["kind"] == "redirect"
    assert started["url"] == multicard.checkout_url
    assert started["charge"] == "" and started["wait_url"]
    # Only the empty confirmation was tried, and refused.
    assert multicard.confirmed == [{}]
    db.expire_all()
    assert db.scalar(select(Invoice.status)) == "pending"


def test_renewal_with_a_page_to_confirm_still_waits_for_the_owner(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    multicard.checkout_url = "https://checkout.multicard.uz/payment/p1"

    assert services.charge_due(db, now=utcnow()) == 1
    # Only the empty confirmation was tried, and refused.
    assert multicard.confirmed == [{}]
    shown = client.get("/api/v1/billing/card", headers=auth).json()
    assert shown["last_charge"]["outcome"] == "needs_code"


def test_a_code_confirms_only_the_bill_it_was_sent_for(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    first = _pay(client, auth).json()
    other = encrypt("1234567890:p1").decode()

    crossed = client.post(
        f"/api/v1/billing/invoice/{first['number']}/confirm",
        json={"charge": other, "code": "50112"},
        headers=auth,
    )
    forged = client.post(
        f"/api/v1/billing/invoice/{first['number']}/confirm",
        json={"charge": "p1", "code": "50112"},
        headers=auth,
    )

    assert crossed.status_code == 400 and crossed.json()["code"] == "card_code_stale"
    assert forged.status_code == 400 and forged.json()["code"] == "card_code_stale"
    assert multicard.confirmed == [{}]


def _later(monkeypatch: pytest.MonkeyPatch, seconds: int) -> None:
    then = utcnow() + timedelta(seconds=seconds)
    monkeypatch.setattr("app.modules.billing.routers.utcnow", lambda: then)


def test_a_new_code_is_a_new_payment_after_a_minute(
    client: TestClient,
    db: Session,
    multicard: FakeMulticard,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    started = _pay(client, auth).json()
    assert started["kind"] == "code" and started["resend_in"] == 60
    url = f"/api/v1/billing/invoice/{started['number']}"

    early = client.post(
        f"{url}/resend", json={"charge": started["charge"]}, headers=auth
    )
    assert early.status_code == 429
    assert early.json()["code"] == "card_code_too_soon"
    assert len(multicard.payments) == 1

    _later(monkeypatch, 61)
    again = client.post(
        f"{url}/resend", json={"charge": started["charge"]}, headers=auth
    )

    assert again.status_code == 200, again.text
    resent = again.json()
    assert resent["kind"] == "code" and resent["resend_in"] == 60
    assert resent["number"] == started["number"]
    assert resent["charge"] != started["charge"]
    assert list(multicard.payments) == ["p1", "p2"]
    assert multicard.dropped == ["p1"]
    assert multicard.payments["p2"]["invoice_id"] == started["number"]
    paid = client.post(
        f"{url}/confirm",
        json={"charge": resent["charge"], "code": "50112"},
        headers=auth,
    )
    assert paid.status_code == 200, paid.text
    assert multicard.callbacks[-1].json()["success"] is True
    db.expire_all()
    assert db.scalar(select(Invoice.status)) == "paid"


def test_codes_stop_after_five_sends(
    client: TestClient,
    db: Session,
    multicard: FakeMulticard,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    started = _pay(client, auth).json()
    url = f"/api/v1/billing/invoice/{started['number']}/resend"
    charge = started["charge"]
    for step in range(1, 5):
        _later(monkeypatch, 61 * step)
        answer = client.post(url, json={"charge": charge}, headers=auth)
        assert answer.status_code == 200, answer.text
        charge = answer.json()["charge"]

    _later(monkeypatch, 61 * 5)
    over = client.post(url, json={"charge": charge}, headers=auth)

    assert over.status_code == 400 and over.json()["code"] == "card_code_limit"
    assert len(multicard.payments) == 5


def test_a_new_code_is_asked_only_for_its_own_bill(
    client: TestClient,
    db: Session,
    multicard: FakeMulticard,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    started = _pay(client, auth).json()
    _later(monkeypatch, 61)

    forged = client.post(
        f"/api/v1/billing/invoice/{started['number']}/resend",
        json={"charge": encrypt("1234567890:p1").decode()},
        headers=auth,
    )
    stranger = client.post(
        f"/api/v1/billing/invoice/{started['number']}/resend",
        json={"charge": started["charge"]},
        headers=sign_up(client, email="stranger@example.uz"),
    )

    assert forged.status_code == 400 and forged.json()["code"] == "card_code_stale"
    assert stranger.status_code == 404
    assert len(multicard.payments) == 1


def test_a_card_that_stops_asking_for_a_code_is_taken_on_resend(
    client: TestClient,
    db: Session,
    multicard: FakeMulticard,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    _plan_running_out(db)
    multicard.otp_hash = "abc"
    started = _pay(client, auth).json()
    multicard.otp_hash = None
    _later(monkeypatch, 61)

    answer = client.post(
        f"/api/v1/billing/invoice/{started['number']}/resend",
        json={"charge": started["charge"]},
        headers=auth,
    )

    assert answer.status_code == 200, answer.text
    assert answer.json()["kind"] == "wait" and answer.json()["charge"] == ""
    db.expire_all()
    assert db.scalar(select(Invoice.status)) == "paid"


def test_a_refused_card_says_why_and_no_card_is_not_found(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _plan_running_out(db)

    none = _pay(client, auth)
    assert none.status_code == 404 and none.json()["code"] == "autopay_card_not_found"

    _bound(client, auth)
    multicard.confirm = {"error": {"code": "ERROR_INSUFFICIENT_FUNDS"}}
    refused = _pay(client, auth)

    assert refused.status_code == 400 and refused.json()["code"] == "card_declined"
    assert refused.json()["detail"] == "Kartada mablag' yetarli emas."
    db.expire_all()
    assert set(db.scalars(select(Invoice.status))) == {"pending"}


def test_a_card_bound_from_a_checkout_comes_back_to_it_with_autopay_as_chosen(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)

    opened = client.post(
        "/api/v1/billing/card/bind",
        json={
            "consent": True,
            "phone": "998901234567",
            "autopay": False,
            "back": "/app/billing/checkout/?plan=pro",
        },
        headers=auth,
    )
    assert opened.status_code == 200, opened.text
    client.post("/webhooks/cards/multicard", json={"payer_id": SESSION})

    sent = multicard.binds[-1]
    assert sent["redirect_url"].endswith("/app/billing/checkout/?plan=pro&card=bound")
    assert sent["redirect_decline_url"].endswith("plan=pro&card=declined")
    shown = client.get("/api/v1/billing/card", headers=auth).json()
    assert shown["card"] is not None and shown["autopay"] is False


@pytest.mark.parametrize("card_type", ["", "humo", "uzcard", "visa"])
def test_no_phone_is_sent_for_any_card(
    client: TestClient, multicard: FakeMulticard, card_type: str
) -> None:
    """Multicard refuses a card whose SMS number differs from a given phone."""
    auth = sign_up(client)

    opened = client.post(
        "/api/v1/billing/card/bind",
        json={"consent": True, "phone": "998901234567", "card_type": card_type},
        headers=auth,
    )

    assert opened.status_code == 200, opened.text
    assert "phone" not in multicard.binds[-1]


@pytest.mark.parametrize(
    "back", ["https://evil.example/app/", "//evil.example", "/app//x", "/office/", ""]
)
def test_only_a_cabinet_path_is_returned_to(back: str) -> None:
    assert services.return_paths(back) == (
        "/app/billing?card=bound",
        "/app/billing?card=declined",
    )


def test_a_renewal_from_the_card_carries_the_bought_pages(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    _bound(client, auth)
    subscription = _plan_running_out(db)
    subscription.plan.extra_page_price = 249000
    db.commit()
    bought = client.post(
        "/api/v1/billing/pages", json={"count": 1, "card": True}, headers=auth
    )
    assert bought.status_code == 200, bought.text

    assert services.charge_due(db, now=utcnow()) == 1

    db.expire_all()
    renewal = db.scalar(select(Invoice).where(Invoice.kind == "plan"))
    assert renewal is not None and renewal.status == "paid"
    # The plan and the page bought beside it, in one debit.
    assert renewal.pages == 1
    assert renewal.amount_minor == 490000_00 + 249000_00


def test_a_card_callback_is_read_however_multicard_wraps_the_session(
    client: TestClient, db: Session, multicard: FakeMulticard
) -> None:
    auth = sign_up(client)
    client.post(
        "/api/v1/billing/card/bind",
        headers=auth,
        json={"consent": True, "phone": "998901234567"},
    )

    reported = client.post(
        "/webhooks/cards/multicard",
        content=f"payer_id={SESSION}&card_token=secret",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert reported.status_code == 200, reported.text
    card = db.scalar(select(SavedCard))
    assert card is not None and card.status == "active"


def test_a_card_callback_without_a_session_is_logged_without_its_token(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        reported = client.post(
            "/webhooks/cards/multicard",
            json={"card_token": "secret-token", "status": "draft"},
        )

    assert reported.status_code == 400
    assert "draft" in caplog.text
    assert "secret-token" not in caplog.text
