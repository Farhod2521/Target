"""telegramkit.login: Log In with Telegram's address, the code trade and the
ID token's checks. An ``httpx.MockTransport`` answers the token endpoint."""

import base64
import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from telegramkit import TelegramLoginError
from telegramkit.login import login_profile, login_url

NOW = 1_800_000_000.0
GOOD = {
    "iss": "https://oauth.telegram.org",
    "aud": "123456",
    "sub": "abc",
    "exp": NOW + 3600,
    "id": 42,
    "name": "Vali Aliyev",
    "preferred_username": "vali",
    "phone_number": "998901234567",
    "phone_number_verified": True,
}


def id_token(claims: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"header.{encoded.rstrip('=')}.signature"


def profile(
    claims: dict[str, Any] | None,
    seen: list[httpx.Request] | None = None,
    status: int = 200,
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body: dict[str, Any] = {"access_token": "t", "token_type": "Bearer"}
        if claims is not None:
            body["id_token"] = id_token(claims)
        if status != 200:
            body = {"error": "invalid_grant"}
        return httpx.Response(status, json=body)

    return login_profile(
        client_id="123456",
        client_secret="secret",
        redirect_uri="https://example.test/cb",
        code="code-1",
        verifier="v" * 64,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        now=NOW,
    )


def test_the_address_carries_the_pkce_challenge_and_the_scopes() -> None:
    url = urlparse(
        login_url(
            client_id="123456",
            redirect_uri="https://example.test/cb",
            state="s",
            verifier="v" * 64,
        )
    )
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://oauth.telegram.org/auth"
    query = parse_qs(url.query)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(b"v" * 64).digest())
    assert query["code_challenge"] == [challenge.rstrip(b"=").decode()]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["openid profile phone telegram:bot_access"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["s"]


def test_the_code_is_traded_with_the_secret_and_the_verifier() -> None:
    seen: list[httpx.Request] = []
    login = profile(GOOD, seen)
    assert (login.id, login.name, login.username, login.phone) == (
        42,
        "Vali Aliyev",
        "vali",
        "998901234567",
    )
    assert "Vali" not in repr(login) and "998" not in repr(login)
    sent = parse_qs(seen[0].content.decode())
    assert sent["code_verifier"] == ["v" * 64]
    assert sent["grant_type"] == ["authorization_code"]
    basic = base64.b64encode(b"123456:secret").decode()
    assert seen[0].headers["authorization"] == f"Basic {basic}"


def test_a_number_telegram_says_is_unverified_is_dropped() -> None:
    assert profile(GOOD | {"phone_number_verified": False}).phone == ""
    no_phone = {k: v for k, v in GOOD.items() if not k.startswith("phone")}
    assert profile(no_phone).phone == ""


@pytest.mark.parametrize(
    "claims",
    [
        None,
        GOOD | {"aud": "999"},
        GOOD | {"iss": "https://evil.test"},
        GOOD | {"exp": NOW - 3600},
        {k: v for k, v in GOOD.items() if k not in ("id", "sub")},
    ],
    ids=["no-id-token", "other-bot", "other-issuer", "expired", "nobody"],
)
def test_a_token_that_does_not_hold_is_refused(claims: dict[str, Any] | None) -> None:
    with pytest.raises(TelegramLoginError):
        profile(claims)


def test_a_refused_code_is_an_error() -> None:
    with pytest.raises(TelegramLoginError):
        profile(GOOD, status=400)
