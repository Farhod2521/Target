"""googlekit.login: the sign-in address and the ID token's checks.

An ``httpx.MockTransport`` answers the token endpoint, like the rest of
this directory.
"""

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from googlekit import GoogleAPIError, login_profile, login_url

NOW = 1_800_000_000.0
GOOD = {
    "aud": "cid",
    "iss": "https://accounts.google.com",
    "exp": NOW + 3600,
    "sub": "1234567890",
    "email": "Owner@Gmail.com",
    "email_verified": True,
    "name": " Ali Valiyev ",
}


def id_token(claims: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"header.{encoded.rstrip('=')}.signature"


def profile(
    claims: dict[str, Any] | None, seen: list[httpx.Request] | None = None
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = {"access_token": "ya29.x"}
        if claims is not None:
            body["id_token"] = id_token(claims)
        return httpx.Response(200, json=body)

    return login_profile(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://example.test/cb",
        code="code-1",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        now=NOW,
    )


def test_the_address_asks_for_who_and_lets_one_pick() -> None:
    query = parse_qs(
        urlparse(
            login_url(
                client_id="cid", redirect_uri="https://example.test/cb", state="s"
            )
        ).query
    )
    assert query["scope"] == ["openid email profile"]
    assert query["prompt"] == ["select_account"]
    assert query["state"] == ["s"]
    assert "access_type" not in query


def test_a_good_token_names_the_person() -> None:
    seen: list[httpx.Request] = []
    found = profile(GOOD, seen)
    assert (found.subject, found.email, found.email_verified, found.name) == (
        "1234567890",
        "owner@gmail.com",
        True,
        "Ali Valiyev",
    )
    assert parse_qs(seen[0].content.decode())["grant_type"] == ["authorization_code"]
    assert "owner@gmail.com" not in repr(found)


def test_verified_may_come_as_a_string() -> None:
    assert profile(GOOD | {"email_verified": "true"}).email_verified is True
    assert profile(GOOD | {"email_verified": "false"}).email_verified is False
    assert (
        profile({k: v for k, v in GOOD.items() if k != "email_verified"}).email_verified
        is False
    )


@pytest.mark.parametrize(
    "claims",
    [
        None,
        GOOD | {"aud": "another-app"},
        GOOD | {"iss": "https://evil.test"},
        GOOD | {"exp": NOW - 3600},
        GOOD | {"sub": ""},
    ],
    ids=["no-token", "audience", "issuer", "expired", "nobody"],
)
def test_a_token_that_does_not_hold_is_refused(claims: dict[str, Any] | None) -> None:
    with pytest.raises(GoogleAPIError):
        profile(claims)


def test_a_token_a_little_past_its_time_still_holds() -> None:
    assert profile(GOOD | {"exp": NOW - 60}).subject == "1234567890"
