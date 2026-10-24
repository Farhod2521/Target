"""What Click's protocol is pinned to.

The signature is the interesting part. It is an MD5 over a fixed field
order with the secret spliced in after ``service_id``, and every way of
getting it wrong - a field swapped, the amount re-rendered, the secret in
the wrong slot - produces a digest that matches nothing. Which looks
exactly like a wrong secret key, and is the failure this file exists to
make impossible to ship.
"""

import hashlib

import pytest
from paykit import (
    Allowed,
    CheckoutRequest,
    MalformedCallback,
    RawRequest,
    Refused,
    Settled,
    TransactionRecord,
)
from paykit.click import ClickAdapter

SERVICE = "12345"
MERCHANT = "54321"
SECRET = "shop-secret"
NUMBER = "1234567890"
AMOUNT_MINOR = 4_900_000
AMOUNT_UNITS = "49000.00"
SIGN_TIME = "2026-08-29 10:00:00"
CLICK_TRANS = "998877"


@pytest.fixture
def adapter() -> ClickAdapter:
    return ClickAdapter(
        service_id=SERVICE,
        merchant_id=MERCHANT,
        secret_key=SECRET,
        decimal_places=2,
    )


@pytest.fixture
def record() -> TransactionRecord:
    from datetime import UTC, datetime

    return TransactionRecord(
        number=NUMBER,
        reference="112233445566",
        external_id=CLICK_TRANS,
        state="created",
        amount_minor=AMOUNT_MINOR,
        created_at=datetime(2026, 8, 29, 10, 0, tzinfo=UTC),
    )


def _prepare(**overrides: str) -> dict[str, str]:
    """A signed Prepare post, with whatever the caller wants changed."""
    form = {
        "click_trans_id": CLICK_TRANS,
        "service_id": SERVICE,
        "merchant_trans_id": NUMBER,
        "amount": AMOUNT_UNITS,
        "action": "0",
        "error": "0",
        "sign_time": SIGN_TIME,
    }
    form |= overrides
    digest = hashlib.md5(
        (
            form["click_trans_id"]
            + form["service_id"]
            + SECRET
            + form["merchant_trans_id"]
            + form["amount"]
            + form["action"]
            + form["sign_time"]
        ).encode()
    ).hexdigest()
    return form | {"sign_string": overrides.get("sign_string", digest)}


def _complete(**overrides: str) -> dict[str, str]:
    """A signed Complete post. One field more in the digest than Prepare."""
    form = _prepare(action="1") | {"merchant_prepare_id": "112233445566"}
    form |= overrides
    digest = hashlib.md5(
        (
            form["click_trans_id"]
            + form["service_id"]
            + SECRET
            + form["merchant_trans_id"]
            + form["merchant_prepare_id"]
            + form["amount"]
            + form["action"]
            + form["sign_time"]
        ).encode()
    ).hexdigest()
    return form | {"sign_string": overrides.get("sign_string", digest)}


def test_checkout_quotes_the_amount_in_whole_currency(
    adapter: ClickAdapter,
) -> None:
    """The payer reads this figure on Click's page, so it is not minor units."""
    checkout = adapter.checkout(
        request=CheckoutRequest(
            number=NUMBER,
            amount_minor=AMOUNT_MINOR,
            decimal_places=2,
            return_url="https://example.uz/back",
        )
    )

    assert checkout.kind == "redirect"
    assert f"amount={AMOUNT_UNITS}" in checkout.url
    assert f"transaction_param={NUMBER}" in checkout.url
    assert "return_url=https://example.uz/back" in checkout.url


def test_prepare_and_complete_sign_different_field_lists(
    adapter: ClickAdapter,
) -> None:
    """Complete adds ``merchant_prepare_id``; using one list for both fails."""
    assert adapter.authenticate(request=RawRequest(form=_prepare()))
    assert adapter.authenticate(request=RawRequest(form=_complete()))


def test_a_tampered_amount_does_not_authenticate(adapter: ClickAdapter) -> None:
    """The digest covers the amount, which is what stops an edited link."""
    form = _prepare()
    form["amount"] = "1.00"
    assert not adapter.authenticate(request=RawRequest(form=form))


def test_an_unknown_action_does_not_authenticate(adapter: ClickAdapter) -> None:
    """There is no correct digest for a step that does not exist."""
    assert not adapter.authenticate(request=RawRequest(form=_prepare(action="9")))


def test_prepare_is_a_hold(adapter: ClickAdapter) -> None:
    parsed = adapter.parse(request=RawRequest(form=_prepare()))
    assert parsed.command == "create"
    assert parsed.number == NUMBER
    assert parsed.external_id == CLICK_TRANS


def test_complete_with_no_error_is_a_settlement(adapter: ClickAdapter) -> None:
    parsed = adapter.parse(request=RawRequest(form=_complete()))
    assert parsed.command == "perform"


def test_complete_with_a_negative_error_is_a_cancellation(
    adapter: ClickAdapter,
) -> None:
    """The field that decides whether a month was sold. Read as data, not noise."""
    parsed = adapter.parse(request=RawRequest(form=_complete(error="-5")))
    assert parsed.command == "cancel"
    assert parsed.cancel_reason == -5


def test_the_amount_is_converted_back_to_minor_units(
    adapter: ClickAdapter,
) -> None:
    """``"49000.00"`` is 4 900 000, and a hundredfold error here is silent."""
    parsed = adapter.parse(request=RawRequest(form=_prepare()))
    assert parsed.amount_minor == AMOUNT_MINOR


def test_an_amount_that_is_not_a_number_is_malformed(
    adapter: ClickAdapter,
) -> None:
    """Malformed rather than a mismatch: we could not read it, not disagree with it."""
    with pytest.raises(MalformedCallback):
        adapter.parse(request=RawRequest(form=_prepare(amount="лот")))


def test_prepare_answers_with_merchant_prepare_id(
    adapter: ClickAdapter, record: TransactionRecord
) -> None:
    """Click stores this and sends it back on Complete, in an integer column."""
    request = adapter.parse(request=RawRequest(form=_prepare()))
    body = adapter.render(request=request, outcome=Settled(transaction=record)).body

    assert body["merchant_prepare_id"] == 112233445566
    assert body["click_trans_id"] == 998877
    assert body["merchant_trans_id"] == NUMBER
    assert body["error"] == 0


def test_complete_answers_with_merchant_confirm_id(
    adapter: ClickAdapter, record: TransactionRecord
) -> None:
    """The same value under the name the second step expects."""
    request = adapter.parse(request=RawRequest(form=_complete()))
    body = adapter.render(request=request, outcome=Settled(transaction=record)).body

    assert body["merchant_confirm_id"] == 112233445566
    assert "merchant_prepare_id" not in body


def test_a_refusal_carries_clicks_own_number(adapter: ClickAdapter) -> None:
    request = adapter.parse(request=RawRequest(form=_prepare()))
    body = adapter.render(
        request=request, outcome=Refused(reason="amount_mismatch")
    ).body

    assert body["error"] == -2
    assert body["error_note"] == "Incorrect parameter amount"


def test_a_question_this_protocol_cannot_ask_is_refused_not_raised(
    adapter: ClickAdapter,
) -> None:
    """Click never asks ``check``, and a 500 on the payment path is worse."""
    request = adapter.parse(request=RawRequest(form=_prepare()))
    body = adapter.render(request=request, outcome=Allowed()).body
    assert body["error"] == -3


def test_a_bad_signature_is_answered_inside_a_200(adapter: ClickAdapter) -> None:
    answer = adapter.refuse_unauthenticated(request=RawRequest(form=_prepare()))
    assert answer.status_code == 200
    assert answer.body["error"] == -1
    assert answer.body["error_note"] == "SIGN CHECK FAILED"
