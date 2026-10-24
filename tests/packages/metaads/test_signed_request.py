"""metaads.signed_request: the only thing standing between a stranger
and an erasure request filed against someone else's account.

No database, no Django. The app secret is an argument, which is what lets
these run in milliseconds and cover the failure modes exhaustively.
"""

import base64
import hmac
import json
from hashlib import sha256

import pytest
from metaads.signed_request import (
    SignedRequestError,
    build_signed_request,
    parse_signed_request,
)

SECRET = "app-secret-for-tests"
PAYLOAD = {
    "algorithm": "HMAC-SHA256",
    "user_id": "1122334455",
    "issued_at": 1_700_000_000,
}


def test_valid_request_is_parsed() -> None:
    raw = build_signed_request(PAYLOAD, app_secret=SECRET)

    result = parse_signed_request(raw, app_secret=SECRET)

    assert result.user_id == "1122334455"
    assert result.algorithm == "HMAC-SHA256"
    assert result.issued_at == 1_700_000_000


def test_wrong_secret_is_rejected() -> None:
    """The whole point: a payload we did not sign must not be trusted."""
    raw = build_signed_request(PAYLOAD, app_secret="somebody-elses-secret")

    with pytest.raises(SignedRequestError):
        parse_signed_request(raw, app_secret=SECRET)


def test_tampered_payload_is_rejected() -> None:
    """Swapping the user id after signing must invalidate the signature."""
    raw = build_signed_request(PAYLOAD, app_secret=SECRET)
    signature, _, _ = raw.partition(".")
    forged_payload = (
        base64.urlsafe_b64encode(
            json.dumps({**PAYLOAD, "user_id": "9999999999"}).encode()
        )
        .rstrip(b"=")
        .decode()
    )

    with pytest.raises(SignedRequestError):
        parse_signed_request(f"{signature}.{forged_payload}", app_secret=SECRET)


def test_empty_app_secret_is_rejected() -> None:
    """A misconfigured deployment must fail closed, not verify against ''."""
    raw = build_signed_request(PAYLOAD, app_secret="")

    with pytest.raises(SignedRequestError):
        parse_signed_request(raw, app_secret="")


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("", id="empty"),
        pytest.param("no-separator-here", id="no-separator"),
        pytest.param(".payload", id="no-signature"),
        pytest.param("signature.", id="no-payload"),
        pytest.param("!!!.@@@", id="not-base64"),
    ],
)
def test_malformed_input_is_rejected(raw: str) -> None:
    with pytest.raises(SignedRequestError):
        parse_signed_request(raw, app_secret=SECRET)


def test_payload_that_is_not_json_is_rejected() -> None:
    """Signed correctly, but the body is garbage.

    The signature is computed over the garbage on purpose: otherwise the test
    would pass because verification failed, and never reach the JSON parse it
    is supposed to cover.
    """
    body = base64.urlsafe_b64encode(b"not json").rstrip(b"=").decode()
    digest = hmac.new(SECRET.encode(), body.encode(), sha256).digest()
    signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    with pytest.raises(SignedRequestError):
        parse_signed_request(f"{signature}.{body}", app_secret=SECRET)


def test_unsupported_algorithm_is_rejected() -> None:
    """An attacker who picks the algorithm picks a weak one."""
    raw = build_signed_request(
        {**PAYLOAD, "algorithm": "NONE"},
        app_secret=SECRET,
    )

    with pytest.raises(SignedRequestError):
        parse_signed_request(raw, app_secret=SECRET)


def test_missing_user_id_is_rejected() -> None:
    """Without a user id there is nobody to file the request against."""
    raw = build_signed_request(
        {"algorithm": "HMAC-SHA256", "issued_at": 1}, app_secret=SECRET
    )

    with pytest.raises(SignedRequestError):
        parse_signed_request(raw, app_secret=SECRET)


def test_non_integer_issued_at_becomes_none() -> None:
    """Meta's clock is advisory. A malformed one is dropped, not fatal."""
    raw = build_signed_request(
        {"algorithm": "HMAC-SHA256", "user_id": "1", "issued_at": "yesterday"},
        app_secret=SECRET,
    )

    assert parse_signed_request(raw, app_secret=SECRET).issued_at is None


def test_signature_survives_missing_base64_padding() -> None:
    """Meta strips '=' padding; restoring it is our job, not a failure."""
    raw = build_signed_request(PAYLOAD, app_secret=SECRET)

    assert "=" not in raw
    assert parse_signed_request(raw, app_secret=SECRET).user_id == "1122334455"
