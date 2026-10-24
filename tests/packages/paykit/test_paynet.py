"""What Paynet's adapter is pinned to, and what deliberately is not.

The contract is not signed. :mod:`paykit.paynet.codes` says which method
names and which numbers are provisional because of it, and this file
tests around them: the envelope, the credential, the reading of a request
into a command, and the one thing that makes this provider different from
the two card gateways - there is nothing to redirect to.

A test that asserted a provisional number would be a test that has to be
edited the day the contract arrives, which is the day the numbers are
*supposed* to change. So none of them do.
"""

import base64
import json

import pytest
from paykit import CheckoutRequest, MalformedCallback, RawRequest, Refused
from paykit.paynet import PaynetAdapter

USERNAME = "merchant"
PASSWORD = "merchant-secret"
SERVICE = "targetolog"
NUMBER = "1234567890"


@pytest.fixture
def adapter() -> PaynetAdapter:
    return PaynetAdapter(username=USERNAME, password=PASSWORD, service_id=SERVICE)


def _call(method: str, params: dict) -> RawRequest:
    credential = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    return RawRequest(
        headers={"authorization": f"Basic {credential}"},
        body=json.dumps({"method": method, "params": params, "id": 3}).encode(),
    )


def test_checkout_is_a_number_to_quote_not_a_page_to_open(
    adapter: PaynetAdapter,
) -> None:
    """The difference the whole two-shaped ``Checkout`` exists for.

    An agent network takes cash at a counter. There is no card screen to
    send anybody to, and a port that assumed a URL would have needed a
    second port for this.
    """
    checkout = adapter.checkout(
        request=CheckoutRequest(number=NUMBER, amount_minor=4_900_000, decimal_places=2)
    )

    assert checkout.kind == "reference"
    assert checkout.reference == NUMBER
    assert checkout.url == ""


def test_the_reference_is_the_invoice_number_itself(
    adapter: PaynetAdapter,
) -> None:
    """One number for one bill. A second identity is a second support search."""
    checkout = adapter.checkout(
        request=CheckoutRequest(number=NUMBER, amount_minor=1, decimal_places=2)
    )
    assert checkout.reference == NUMBER


def test_authenticate_accepts_the_merchant_credential(
    adapter: PaynetAdapter,
) -> None:
    assert adapter.authenticate(request=_call("CheckTransaction", {}))


def test_authenticate_rejects_another_password(adapter: PaynetAdapter) -> None:
    wrong = base64.b64encode(f"{USERNAME}:nope".encode()).decode()
    assert not adapter.authenticate(
        request=RawRequest(headers={"Authorization": f"Basic {wrong}"}, body=b"{}")
    )


def test_a_settlement_may_name_its_own_invoice(adapter: PaynetAdapter) -> None:
    """What lets a counter payment open an attempt nobody held first.

    The rule in the settle service is about the request naming a bill, not
    about anybody's name - and this is the request that does.
    """
    parsed = adapter.parse(
        request=_call(
            "PerformTransaction",
            {
                "transactionId": "pn-1",
                "amount": 4_900_000,
                "account": {"number": NUMBER},
            },
        )
    )

    assert parsed.command == "perform"
    assert parsed.number == NUMBER
    assert parsed.external_id == "pn-1"


def test_an_unknown_method_is_malformed(adapter: PaynetAdapter) -> None:
    with pytest.raises(MalformedCallback):
        adapter.parse(request=_call("Whatever", {}))


def test_a_refusal_keeps_the_json_rpc_envelope(adapter: PaynetAdapter) -> None:
    """The envelope is protocol, not contract, so it is safe to pin."""
    request = adapter.parse(request=_call("CheckTransaction", {}))
    answer = adapter.render(
        request=request, outcome=Refused(reason="transaction_not_found")
    )

    assert answer.status_code == 200
    assert answer.body["jsonrpc"] == "2.0"
    assert answer.body["id"] == 3
    assert "code" in answer.body["error"]
