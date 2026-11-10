"""googlekit.service_account: the key as the .env holds it, and the signed
request that trades it for a token. No network: a MockTransport answers."""

import base64
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from googlekit import (
    SCOPE_SPREADSHEETS,
    AccessRevoked,
    GoogleAPIError,
    read_key,
    service_token,
)

_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = _PRIVATE.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
KEY = {
    "type": "service_account",
    "client_email": "sheets@project.iam.gserviceaccount.com",
    "private_key_id": "kid-1",
    "private_key": PEM,
    "token_uri": "https://oauth2.googleapis.com/token",
}


def answering(
    payload: dict[str, Any], *, status: int = 200, seen: list[httpx.Request]
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_key_reads_as_json_or_as_base64() -> None:
    text = json.dumps(KEY)

    assert read_key(text) == KEY
    assert read_key(base64.b64encode(text.encode()).decode()) == KEY
    assert read_key(f"  {text}\n") == KEY


@pytest.mark.parametrize(
    "text", ["", "not base64 !!", json.dumps({"client_email": "x"}), "[1, 2]"]
)
def test_a_key_that_cannot_sign_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        read_key(text)


def test_the_signed_request_names_the_account_scope_and_audience() -> None:
    seen: list[httpx.Request] = []
    http = answering({"access_token": "at-1", "expires_in": 3599}, seen=seen)

    token = service_token(key=KEY, now=1_000_000, http=http)

    assert token == "at-1"
    form = parse_qs(seen[0].content.decode())
    assert str(seen[0].url) == KEY["token_uri"]
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    assertion = form["assertion"][0]
    assert jwt.get_unverified_header(assertion)["kid"] == "kid-1"
    claims = jwt.decode(
        assertion,
        _PRIVATE.public_key(),
        algorithms=["RS256"],
        audience=KEY["token_uri"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims == {
        "iss": KEY["client_email"],
        "scope": SCOPE_SPREADSHEETS,
        "aud": KEY["token_uri"],
        "iat": 1_000_000,
        "exp": 1_003_600,
    }
    assert "Authorization" not in seen[0].headers


def test_a_refused_key_and_an_empty_answer_raise() -> None:
    seen: list[httpx.Request] = []
    refused = answering({"error": "invalid_grant"}, status=400, seen=seen)
    with pytest.raises(AccessRevoked):
        service_token(key=KEY, http=refused)

    with pytest.raises(GoogleAPIError):
        service_token(key=KEY, http=answering({}, seen=seen))
