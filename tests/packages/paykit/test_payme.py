"""What Payme's protocol is pinned to.

Every assertion here is about a shape somebody else chose. The value of
pinning them is that a mistake in any one is silent in production: a
checkout link with the wrong separator opens a page that says the order
does not exist, and a result body missing ``perform_time`` is refused by a
validator whose message never reaches us.

No database and no Django, like every test under ``tests/packages``.
"""

import base64
import json
from datetime import UTC, datetime

import pytest
from paykit import (
    Allowed,
    CheckoutRequest,
    MalformedCallback,
    RawRequest,
    Refused,
    Settled,
    Statement,
    TransactionRecord,
)
from paykit.payme import PaymeAdapter
from paykit.payme.codes import (
    INSUFFICIENT_PRIVILEGE,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
)

MERCHANT = "5f3e0a1b2c3d4e5f60718293"
KEY = "a-very-secret-merchant-key"
NUMBER = "1234567890"
AMOUNT = 4_900_000


@pytest.fixture
def adapter() -> PaymeAdapter:
    return PaymeAdapter(merchant_id=MERCHANT, key=KEY, account_field="order_id")


@pytest.fixture
def record() -> TransactionRecord:
    return TransactionRecord(
        number=NUMBER,
        reference="998877665544",
        external_id="65a1b2c3d4e5f60718293a4b",
        state="created",
        amount_minor=AMOUNT,
        created_at=datetime(2026, 8, 29, 10, 0, tzinfo=UTC),
    )


def _call(method: str, params: dict, rpc_id: int = 7) -> RawRequest:
    """One JSON-RPC request with a valid credential on it."""
    credential = base64.b64encode(f"Paycom:{KEY}".encode()).decode()
    return RawRequest(
        headers={"Authorization": f"Basic {credential}"},
        body=json.dumps({"method": method, "params": params, "id": rpc_id}).encode(),
    )


def test_checkout_encodes_the_documented_parameter_string(
    adapter: PaymeAdapter,
) -> None:
    """The link is one base64 segment, and semicolons separate the pairs.

    Decoded here rather than compared as a string, so the test says what
    the format is instead of restating a digest nobody can read.
    """
    checkout = adapter.checkout(
        request=CheckoutRequest(
            number=NUMBER,
            amount_minor=AMOUNT,
            decimal_places=2,
            return_url="https://example.uz/back",
            language="uz",
        )
    )

    assert checkout.kind == "redirect"
    encoded = checkout.url.rsplit("/", 1)[1]
    assert base64.b64decode(encoded).decode() == (
        f"m={MERCHANT};ac.order_id={NUMBER};a={AMOUNT};c=https://example.uz/back;l=uz"
    )


def test_checkout_sends_the_amount_in_minor_units(adapter: PaymeAdapter) -> None:
    """Tiyin is the currency's smallest unit, so nothing is converted.

    The one figure in this package that could be a hundredfold out is the
    one that passes straight through, and this is what says so.
    """
    checkout = adapter.checkout(
        request=CheckoutRequest(number=NUMBER, amount_minor=AMOUNT, decimal_places=2)
    )
    decoded = base64.b64decode(checkout.url.rsplit("/", 1)[1]).decode()
    assert f"a={AMOUNT}" in decoded


def test_authenticate_accepts_the_cashbox_key(adapter: PaymeAdapter) -> None:
    assert adapter.authenticate(request=_call("CheckTransaction", {"id": "x"}))


def test_authenticate_rejects_another_key(adapter: PaymeAdapter) -> None:
    """A wrong key is not authenticated, whatever the body says."""
    wrong = base64.b64encode(b"Paycom:not-the-key").decode()
    request = RawRequest(headers={"Authorization": f"Basic {wrong}"}, body=b"{}")
    assert not adapter.authenticate(request=request)


def test_authenticate_rejects_a_missing_header(adapter: PaymeAdapter) -> None:
    assert not adapter.authenticate(request=RawRequest(body=b"{}"))


@pytest.mark.parametrize(
    ("method", "command"),
    [
        ("CheckPerformTransaction", "check"),
        ("CreateTransaction", "create"),
        ("PerformTransaction", "perform"),
        ("CancelTransaction", "cancel"),
        ("CheckTransaction", "status"),
        ("GetStatement", "statement"),
    ],
)
def test_every_published_method_maps_to_a_command(
    adapter: PaymeAdapter, method: str, command: str
) -> None:
    """All six, because a missing one is a callback that 404s in effect."""
    parsed = adapter.parse(request=_call(method, {}))
    assert parsed.command == command


def test_parse_reads_the_account_field_this_cashbox_uses(
    adapter: PaymeAdapter,
) -> None:
    """The order key is configuration, and the parser has to honour it."""
    parsed = adapter.parse(
        request=_call(
            "CreateTransaction",
            {
                "id": "abc",
                "time": 1_756_000_000_000,
                "amount": AMOUNT,
                "account": {"order_id": NUMBER},
            },
        )
    )
    assert parsed.number == NUMBER
    assert parsed.external_id == "abc"
    assert parsed.amount_minor == AMOUNT
    assert parsed.requested_at == datetime.fromtimestamp(1_756_000_000, tz=UTC)


def test_parse_refuses_a_method_payme_does_not_publish(
    adapter: PaymeAdapter,
) -> None:
    with pytest.raises(MalformedCallback):
        adapter.parse(request=_call("DropDatabase", {}))


def test_parse_refuses_a_body_that_is_not_json(adapter: PaymeAdapter) -> None:
    with pytest.raises(MalformedCallback):
        adapter.parse(request=RawRequest(body=b"<html>"))


def test_check_renders_allow(adapter: PaymeAdapter) -> None:
    request = adapter.parse(request=_call("CheckPerformTransaction", {}))
    answer = adapter.render(request=request, outcome=Allowed())
    assert answer.body["result"] == {"allow": True}
    assert answer.body["id"] == 7


def test_settled_carries_all_three_timestamps(
    adapter: PaymeAdapter, record: TransactionRecord
) -> None:
    """Missing times are zero, never null - their validator reads null as absent."""
    request = adapter.parse(request=_call("CreateTransaction", {}))
    result = adapter.render(request=request, outcome=Settled(transaction=record)).body[
        "result"
    ]

    assert result["create_time"] == 1_787_997_600_000
    assert result["perform_time"] == 0
    assert result["cancel_time"] == 0
    assert result["transaction"] == "998877665544"
    assert result["state"] == 1


def test_a_refund_renders_as_state_minus_two(
    adapter: PaymeAdapter, record: TransactionRecord
) -> None:
    """The distinction the whole refund path rests on, at the wire level."""
    request = adapter.parse(request=_call("CancelTransaction", {}))
    refunded = record.model_copy(
        update={
            "state": "refunded",
            "canceled_at": datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
            "cancel_reason": 5,
        }
    )
    result = adapter.render(
        request=request, outcome=Settled(transaction=refunded)
    ).body["result"]

    assert result["state"] == -2
    assert result["cancel_time"] > 0


def test_check_transaction_carries_the_reason(
    adapter: PaymeAdapter, record: TransactionRecord
) -> None:
    """``CheckTransaction`` requires ``reason``: null while live, the code after."""
    request = adapter.parse(request=_call("CheckTransaction", {}))
    live = adapter.render(request=request, outcome=Settled(transaction=record))
    cancelled = adapter.render(
        request=request,
        outcome=Settled(
            transaction=record.model_copy(
                update={
                    "state": "canceled",
                    "canceled_at": datetime(2026, 8, 29, 11, 0, tzinfo=UTC),
                    "cancel_reason": 3,
                }
            )
        ),
    )

    assert live.body["result"]["reason"] is None
    assert cancelled.body["result"]["reason"] == 3


def test_statement_carries_the_account_and_the_amount(
    adapter: PaymeAdapter, record: TransactionRecord
) -> None:
    """A statement is what they reconcile against, so each row must be findable."""
    request = adapter.parse(
        request=_call(
            "GetStatement", {"from": 1_756_000_000_000, "to": 1_756_100_000_000}
        )
    )
    result = adapter.render(
        request=request, outcome=Statement(transactions=[record])
    ).body["result"]

    entry = result["transactions"][0]
    assert entry["account"] == {"order_id": NUMBER}
    assert entry["amount"] == AMOUNT
    assert entry["id"] == record.external_id


def test_an_unknown_invoice_names_the_account_field(adapter: PaymeAdapter) -> None:
    """``data`` is what tells their page which field to highlight."""
    request = adapter.parse(request=_call("CheckPerformTransaction", {}))
    error = adapter.render(
        request=request, outcome=Refused(reason="invoice_not_found")
    ).body["error"]

    assert error["code"] == -31050
    assert error["data"] == "order_id"
    assert set(error["message"]) == {"uz", "ru", "en"}


def test_a_protocol_error_carries_no_data_field(adapter: PaymeAdapter) -> None:
    """Sending one outside the merchant band makes their validator complain."""
    request = adapter.parse(request=_call("PerformTransaction", {}))
    error = adapter.render(
        request=request, outcome=Refused(reason="transaction_not_found")
    ).body["error"]

    assert error["code"] == -31003
    assert "data" not in error


def test_a_second_transaction_on_a_held_invoice_cannot_be_performed(
    adapter: PaymeAdapter,
) -> None:
    """The sandbox wants -31008 here, outside the band, so no ``data`` either."""
    request = adapter.parse(request=_call("CreateTransaction", {}))
    error = adapter.render(
        request=request, outcome=Refused(reason="invoice_held")
    ).body["error"]

    assert error["code"] == -31008
    assert "data" not in error
    assert set(error["message"]) == {"uz", "ru", "en"}


def test_unauthenticated_is_answered_inside_a_200(adapter: PaymeAdapter) -> None:
    """A non-2xx is read as an outage, which is worse than a clear refusal."""
    answer = adapter.refuse_unauthenticated(request=RawRequest(body=b"{}"))
    assert answer.status_code == 200
    assert answer.body["error"]["code"] == INSUFFICIENT_PRIVILEGE


def test_malformed_tells_a_parse_error_from_an_unknown_method(
    adapter: PaymeAdapter,
) -> None:
    """One code for both would hide a proxy mangling bodies behind a version bump."""
    unreadable = adapter.refuse_malformed(request=RawRequest(body=b"not json"))
    unknown = adapter.refuse_malformed(
        request=RawRequest(body=json.dumps({"method": "Nope"}).encode())
    )

    assert unreadable.body["error"]["code"] == PARSE_ERROR
    assert unknown.body["error"]["code"] == METHOD_NOT_FOUND
