"""What Multicard's protocol is pinned to: the invoice we ask for, and the signatures we accept."""

import hashlib
import json
from typing import Any

import httpx
import pytest
from paykit import (
    CheckoutRequest,
    MalformedCallback,
    ProviderMisconfigured,
    ProviderUnavailable,
    RawRequest,
    Refused,
    Settled,
    TransactionRecord,
)
from paykit.multicard import MulticardAdapter, MulticardClient
from paykit.multicard.adapter import NEVER_STORED

BASE = "https://dev-mesh.multicard.uz"
STORE = "6"
SECRET = "shop-secret"
CALLBACK = "https://api.example.uz/webhooks/pay/multicard"
NUMBER = "1234567890"


class FakeMulticard:
    """A stand-in for Multicard's two endpoints, counting what it was asked."""

    def __init__(self, *, refuse_first_token: bool = False) -> None:
        self.tokens = 0
        self.invoices: list[dict[str, Any]] = []
        self.refuse_first_token = refuse_first_token

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            self.tokens += 1
            assert json.loads(request.content) == {
                "application_id": "app",
                "secret": SECRET,
            }
            return httpx.Response(
                200,
                json={
                    "token": f"t{self.tokens}",
                    "role": "dev",
                    "expiry": "2099-01-01 00:00:00",
                },
            )
        if request.url.path == "/payment/invoice":
            if (
                self.refuse_first_token
                and request.headers["authorization"] == "Bearer t1"
            ):
                return httpx.Response(401, json={"success": False})
            body = json.loads(request.content)
            self.invoices.append(body)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "uuid": "f6339f31",
                        "checkout_url": "https://app.rhmt.uz/invoice/f6339f31",
                    },
                },
            )
        return httpx.Response(404, json={"success": False})


def _adapter(fake: FakeMulticard, **overrides: Any) -> MulticardAdapter:
    client = MulticardClient(
        base_url=BASE,
        application_id="app",
        secret=SECRET,
        transport=httpx.MockTransport(fake),
    )
    options: dict[str, Any] = {
        "client": client,
        "store_id": STORE,
        "secret": SECRET,
        "callback_url": CALLBACK,
        "decimal_places": 2,
        "ofd_mxik": "10305008002000000",
        "ofd_package_code": "1545643",
        "ofd_name": "TargetologAI obunasi",
    }
    return MulticardAdapter(**(options | overrides))


def _callback(**overrides: Any) -> dict[str, Any]:
    body = {
        "store_id": 6,
        "amount": 4_900_000,
        "invoice_id": NUMBER,
        "billing_id": None,
        "payment_time": "2026-10-28 15:00:00",
        "phone": "998901234567",
        "card_pan": "860053******8829",
        "ps": "uzcard",
        "card_token": "secret-card-token",
        "uuid": "f6339f31",
        "receipt_url": "https://ofd.example/receipt",
    } | overrides
    body["sign"] = hashlib.md5(
        f"{body['store_id']}{body['invoice_id']}{body['amount']}{SECRET}".encode()
    ).hexdigest()
    return body


def _raw(body: dict[str, Any], headers: dict[str, str] | None = None) -> RawRequest:
    return RawRequest(headers=headers or {}, body=json.dumps(body).encode())


def test_checkout_creates_an_invoice_in_tiyin_with_a_receipt_line() -> None:
    fake = FakeMulticard()
    adapter = _adapter(fake)
    checkout = adapter.checkout(
        request=CheckoutRequest(
            number=NUMBER,
            amount_minor=4_900_000,
            decimal_places=2,
            return_url="https://targetolog.ai/app/billing/invoice/1",
            language="uz",
            currency="UZS",
            description="TargetologAI obunasi: Pro, 30 kun",
            ttl_seconds=3600,
        )
    )
    assert checkout.kind == "redirect"
    assert checkout.url == "https://app.rhmt.uz/invoice/f6339f31"
    sent = fake.invoices[0]
    assert sent["store_id"] == 6 and sent["amount"] == 4_900_000
    assert sent["invoice_id"] == NUMBER and sent["callback_url"] == CALLBACK
    assert sent["lang"] == "uz" and sent["ttl"] == 3600
    assert sent["ofd"] == [
        {
            "mxik": "10305008002000000",
            "package_code": "1545643",
            "name": "TargetologAI obunasi: Pro, 30 kun",
            "qty": 1,
            "price": 4_900_000,
            "total": 4_900_000,
        }
    ]


def test_whole_som_invoices_are_sent_in_tiyin() -> None:
    fake = FakeMulticard()
    _adapter(fake, decimal_places=0).checkout(
        request=CheckoutRequest(number=NUMBER, amount_minor=49_000, decimal_places=0)
    )
    assert fake.invoices[0]["amount"] == 4_900_000


def test_the_token_is_reused_and_asked_again_when_refused() -> None:
    fake = FakeMulticard(refuse_first_token=True)
    adapter = _adapter(fake)
    request = CheckoutRequest(number=NUMBER, amount_minor=100, decimal_places=2)
    adapter.checkout(request=request)
    assert fake.tokens == 2
    adapter.checkout(request=request)
    assert fake.tokens == 2


def test_only_som_and_never_an_empty_amount() -> None:
    adapter = _adapter(FakeMulticard())
    with pytest.raises(ProviderMisconfigured):
        adapter.checkout(
            request=CheckoutRequest(
                number=NUMBER, amount_minor=100, decimal_places=2, currency="USD"
            )
        )
    with pytest.raises(ProviderMisconfigured):
        adapter.checkout(
            request=CheckoutRequest(number=NUMBER, amount_minor=0, decimal_places=2)
        )


def test_an_unreachable_provider_is_one_error() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = MulticardClient(
        base_url=BASE,
        application_id="app",
        secret=SECRET,
        transport=httpx.MockTransport(broken),
    )
    adapter = _adapter(FakeMulticard(), client=client)
    with pytest.raises(ProviderUnavailable):
        adapter.checkout(
            request=CheckoutRequest(number=NUMBER, amount_minor=100, decimal_places=2)
        )


def test_a_misconfigured_adapter_refuses_to_start() -> None:
    with pytest.raises(ProviderMisconfigured):
        _adapter(FakeMulticard(), secret="")
    with pytest.raises(ProviderMisconfigured):
        _adapter(FakeMulticard(), ofd_mxik="")


def test_the_payment_callback_signature() -> None:
    adapter = _adapter(FakeMulticard())
    assert adapter.authenticate(request=_raw(_callback()))

    forged = _callback()
    forged["amount"] = 100
    assert not adapter.authenticate(request=_raw(forged))

    other_shop = _callback(store_id=7)
    assert not adapter.authenticate(request=_raw(other_shop))

    unsigned = _callback()
    unsigned["sign"] = ""
    assert not adapter.authenticate(request=_raw(unsigned))
    assert not adapter.authenticate(request=RawRequest(body=b"not json"))


def test_the_status_webhook_is_checked_and_never_acted_on() -> None:
    adapter = _adapter(FakeMulticard())
    body = {
        "uuid": "f6339f31",
        "invoice_id": NUMBER,
        "amount": 4_900_000,
        "status": "progress",
    }
    body["sign"] = hashlib.sha1(f"f6339f31{NUMBER}4900000{SECRET}".encode()).hexdigest()
    assert adapter.authenticate(request=_raw(body))
    # The signature leaves ``status`` out: the same signed body says "success" too.
    body["status"] = "success"
    assert adapter.authenticate(request=_raw(body))
    request = adapter.parse(request=_raw(body))
    assert request.command == "status"
    answer = adapter.render(
        request=request, outcome=Refused(reason="transaction_not_found")
    )
    assert answer.status_code == 200
    body["amount"] = 1
    assert not adapter.authenticate(request=_raw(body))


def test_callbacks_only_from_the_allowed_address_when_one_is_set() -> None:
    adapter = _adapter(FakeMulticard(), allowed_ips=["195.158.26.90"])
    assert adapter.authenticate(
        request=_raw(_callback(), {"X-Real-IP": "195.158.26.90"})
    )
    assert not adapter.authenticate(
        request=_raw(_callback(), {"X-Real-IP": "10.0.0.1"})
    )
    assert not adapter.authenticate(request=_raw(_callback()))


def test_parse_reads_a_payment_and_keeps_no_card_token() -> None:
    adapter = _adapter(FakeMulticard())
    request = adapter.parse(request=_raw(_callback()))
    assert request.command == "perform"
    assert request.number == NUMBER and request.external_id == "f6339f31"
    assert request.amount_minor == 4_900_000
    assert request.requested_at is not None
    assert not NEVER_STORED & set(request.raw)


def test_a_fraction_of_a_minor_unit_never_matches_an_invoice() -> None:
    adapter = _adapter(FakeMulticard(), decimal_places=0)
    assert adapter.parse(request=_raw(_callback(amount=4_900_050))).amount_minor == -1
    assert (
        adapter.parse(request=_raw(_callback(amount=4_900_000))).amount_minor == 49_000
    )


def test_parse_refuses_a_callback_it_cannot_read() -> None:
    adapter = _adapter(FakeMulticard())
    with pytest.raises(MalformedCallback):
        adapter.parse(request=_raw(_callback(invoice_id="")))
    with pytest.raises(MalformedCallback):
        adapter.parse(request=_raw(_callback(amount="abc")))


def test_render_lets_a_payment_through_or_returns_the_money() -> None:
    from datetime import UTC, datetime

    adapter = _adapter(FakeMulticard())
    request = adapter.parse(request=_raw(_callback()))
    record = TransactionRecord(
        number=NUMBER,
        reference="1",
        external_id="f6339f31",
        state="performed",
        amount_minor=4_900_000,
        created_at=datetime(2026, 10, 28, tzinfo=UTC),
    )
    ok = adapter.render(request=request, outcome=Settled(transaction=record))
    assert ok.status_code == 200 and ok.body == {"success": True, "message": "OK"}
    refused = adapter.render(request=request, outcome=Refused(reason="amount_mismatch"))
    assert refused.status_code == 200 and refused.body["success"] is False
    assert adapter.refuse_unauthenticated(request=_raw({})).status_code == 403
