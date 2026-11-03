"""Multicard saved cards: binding, charging by token, and what each answer means."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from paykit.errors import ProviderMisconfigured, ProviderUnavailable
from paykit.multicard import (
    CHARGED,
    DECLINED,
    NEEDS_CODE,
    PENDING,
    MulticardAdapter,
    MulticardClient,
)

BASE = "https://dev-mesh.multicard.uz"
STORE = "6"
SECRET = "shop-secret"
CALLBACK = "https://api.example.uz/webhooks/pay/multicard"
TOKEN = "6225f3c93f7a880142782fa4"

Answer = dict[str, Any] | httpx.Response | Callable[[httpx.Request], httpx.Response]


class Wire:
    """Multicard by ``(method, path)``, remembering every request but ``/auth``."""

    def __init__(self, routes: dict[tuple[str, str], Answer]) -> None:
        self.routes = routes
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return httpx.Response(
                200, json={"token": "t", "expiry": "2099-01-01 00:00:00"}
            )
        self.seen.append(request)
        answer = self.routes.get((request.method, request.url.path))
        if answer is None:
            return httpx.Response(
                404, json={"success": False, "error": {"code": "ERROR_NOT_FOUND"}}
            )
        if callable(answer):
            return answer(request)
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json={"success": True, "data": answer})

    def body(self, method: str, path: str) -> dict[str, Any]:
        for request in self.seen:
            if (request.method, request.url.path) == (method, path):
                return dict(json.loads(request.content or b"{}"))
        raise AssertionError(f"{method} {path} was not sent")

    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.seen]


def _adapter(wire: Wire) -> MulticardAdapter:
    return MulticardAdapter(
        client=MulticardClient(
            base_url=BASE,
            application_id="app",
            secret=SECRET,
            transport=httpx.MockTransport(wire),
        ),
        store_id=STORE,
        secret=SECRET,
        callback_url=CALLBACK,
        decimal_places=2,
        ofd_mxik="10305008002000000",
        ofd_package_code="1545643",
        ofd_name="TargetologAI obunasi",
    )


def _refused(code: str, details: str = "") -> httpx.Response:
    return httpx.Response(
        400, json={"success": False, "error": {"code": code, "details": details}}
    )


def _charge(adapter: MulticardAdapter, **changes: Any) -> Any:
    options: dict[str, Any] = {
        "token": TOKEN,
        "number": "1234567890",
        "amount_minor": 49_000_00,
        "decimal_places": 2,
        "currency": "UZS",
        "description": "TargetologAI obunasi: Start, 30 kun",
    }
    return adapter.charge_card(**(options | changes))


CARD = {
    "id": 1,
    "payer_id": "67f8dd24e9800",
    "card_pan": "986027******1519",
    "card_token": TOKEN,
    "phone": "998901234567",
    "holder_name": "ALI VALIYEV",
    "ps": "humo",
    "status": "active",
}


# --- Binding --------------------------------------------------------------


def test_a_binding_page_is_opened_for_our_store() -> None:
    wire = Wire(
        {
            ("POST", "/payment/card/bind"): {
                "session_id": "67f8dd24e9800",
                "form_url": "https://dev-checkout.multicard.uz/card/67f8dd24e9800",
            }
        }
    )

    session = _adapter(wire).start_card_binding(
        phone="998901234567",
        redirect_url="https://site.uz/ok",
        decline_url="https://site.uz/no",
        callback_url="https://api.site.uz/webhooks/cards/multicard",
    )

    assert session.session_id == "67f8dd24e9800"
    assert session.form_url.endswith("/card/67f8dd24e9800")
    assert wire.body("POST", "/payment/card/bind") == {
        "store_id": 6,
        "phone": "998901234567",
        "redirect_url": "https://site.uz/ok",
        "redirect_decline_url": "https://site.uz/no",
        "callback_url": "https://api.site.uz/webhooks/cards/multicard",
    }


def test_a_bound_card_is_read_from_multicard_not_from_its_callback() -> None:
    wire = Wire({("GET", "/payment/card/bind/67f8dd24e9800"): CARD})

    card = _adapter(wire).bound_card(session_id="67f8dd24e9800")

    assert card is not None and card.usable
    assert (card.token, card.pan, card.ps) == (TOKEN, "986027******1519", "humo")


def test_an_unfinished_binding_is_no_card_yet() -> None:
    wire = Wire(
        {("GET", "/payment/card/bind/s1"): _refused("ERROR_NOT_FOUND", "no card")}
    )
    draft = Wire({("GET", "/payment/card/bind/s2"): CARD | {"status": "draft"}})

    assert _adapter(wire).bound_card(session_id="s1") is None
    card = _adapter(draft).bound_card(session_id="s2")
    assert card is not None and not card.usable


def test_a_card_is_revoked_by_its_token() -> None:
    wire = Wire({("DELETE", f"/payment/card/{TOKEN}"): {}})

    _adapter(wire).revoke_card(token=TOKEN)

    assert wire.paths() == [f"DELETE /payment/card/{TOKEN}"]


# --- Charging -------------------------------------------------------------


def test_a_charge_creates_then_confirms_with_an_empty_body() -> None:
    wire = Wire(
        {
            ("POST", "/payment"): {"uuid": "p1", "status": "draft", "otp_hash": None},
            ("PUT", "/payment/p1"): {"uuid": "p1", "status": "success"},
        }
    )

    charge = _charge(_adapter(wire))

    assert (charge.outcome, charge.uuid) == (CHARGED, "p1")
    created = wire.body("POST", "/payment")
    assert created["card"] == {"token": TOKEN}
    assert created["amount"] == 4_900_000
    assert created["store_id"] == 6
    assert created["invoice_id"] == "1234567890"
    # The ordinary payment callback settles it, like a page payment.
    assert created["callback_url"] == CALLBACK
    assert created["ofd"][0]["total"] == 4_900_000
    assert created["ofd"][0]["name"] == "TargetologAI obunasi: Start, 30 kun"
    assert wire.body("PUT", "/payment/p1") == {}


def test_a_shop_that_must_ask_for_a_code_is_never_confirmed() -> None:
    wire = Wire({("POST", "/payment"): {"uuid": "p1", "otp_hash": "abc"}})

    charge = _charge(_adapter(wire))

    assert charge.outcome == NEEDS_CODE
    assert "PUT /payment/p1" not in wire.paths()


def test_a_refused_payment_moves_no_money() -> None:
    wire = Wire({("POST", "/payment"): _refused("ERROR_CARD_NOT_FOUND", "Bad card")})

    charge = _charge(_adapter(wire))

    assert (charge.outcome, charge.code) == (DECLINED, "ERROR_CARD_NOT_FOUND")
    assert charge.uuid == ""


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        (_refused("ERROR_INSUFFICIENT_FUNDS"), DECLINED),
        (_refused("ERROR_DEBIT_UNKNOWN"), PENDING),
        (_refused("ERROR_CALLBACK_TIMEOUT"), PENDING),
        ({"uuid": "p1", "status": "error"}, DECLINED),
        ({"uuid": "p1", "status": "progress"}, PENDING),
    ],
)
def test_a_confirmation_says_how_far_the_debit_got(
    answer: Answer, outcome: str
) -> None:
    wire = Wire(
        {
            ("POST", "/payment"): {"uuid": "p1", "otp_hash": None},
            ("PUT", "/payment/p1"): answer,
        }
    )

    charge = _charge(_adapter(wire))

    assert (charge.outcome, charge.uuid) == (outcome, "p1")


def test_a_lost_confirmation_is_pending_not_failed() -> None:
    def lost(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    wire = Wire(
        {
            ("POST", "/payment"): {"uuid": "p1", "otp_hash": None},
            ("PUT", "/payment/p1"): lost,
        }
    )

    assert _charge(_adapter(wire)).outcome == PENDING


def test_an_unreachable_multicard_is_not_a_decline() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ProviderUnavailable):
        _charge(_adapter(Wire({("POST", "/payment"): down})))


def test_a_pending_charge_is_read_again() -> None:
    wire = Wire({("GET", "/payment/p1"): {"uuid": "p1", "status": "success"}})

    assert _adapter(wire).charge_status(uuid="p1").outcome == CHARGED


def test_only_som_and_never_nothing() -> None:
    adapter = _adapter(Wire({}))

    with pytest.raises(ProviderMisconfigured):
        _charge(adapter, currency="USD")
    with pytest.raises(ProviderMisconfigured):
        _charge(adapter, amount_minor=0)
