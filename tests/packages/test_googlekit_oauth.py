"""googlekit.oauth: the consent URL, the token endpoint, and giving it back.

No Django, no database, no network - an ``httpx.MockTransport`` answers
every request, like the rest of this directory.
"""

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from googlekit import (
    SCOPE_DRIVE_FILE,
    AccessRevoked,
    GoogleAPIError,
    Unavailable,
    authorize_url,
    exchange_code,
    refresh,
    revoke,
)

ACCESS = "ya29.access-token-nobody-should-see"
REFRESH = "1//refresh-token-nobody-should-see"
EMAIL = "owner@example.com"


def answering(
    payload: dict[str, Any] | None = None,
    *,
    status: int = 200,
    seen: list[httpx.Request] | None = None,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload if payload is not None else {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def form(request: httpx.Request) -> dict[str, str]:
    return {
        key: values[0] for key, values in parse_qs(request.content.decode()).items()
    }


def id_token(claims: dict[str, Any]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"header.{encoded.rstrip('=')}.signature"


def exchange(http: httpx.Client) -> Any:
    return exchange_code(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://example.test/cb/",
        code="code-1",
        http=http,
    )


# --- The consent URL -------------------------------------------------------


def query_of(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_consent_asks_for_offline_access_and_forces_the_screen() -> None:
    """Without both, a second connection comes back with no refresh token."""
    query = query_of(
        authorize_url(
            client_id="cid", redirect_uri="https://example.test/cb/", state="s1"
        )
    )

    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"] == ["s1"]
    assert query["redirect_uri"] == ["https://example.test/cb/"]
    assert query["response_type"] == ["code"]


def test_consent_asks_for_nothing_wider_than_drive_file() -> None:
    """One sensitive scope here would send the whole app to verification."""
    query = query_of(
        authorize_url(client_id="cid", redirect_uri="https://x/", state="s")
    )

    assert set(query["scope"][0].split()) == {"openid", "email", SCOPE_DRIVE_FILE}


# --- The token endpoint ----------------------------------------------------


def test_exchange_reads_tokens_scopes_and_the_email() -> None:
    seen: list[httpx.Request] = []
    answer = {
        "access_token": ACCESS,
        "refresh_token": REFRESH,
        "expires_in": 3599,
        "scope": (
            f"openid https://www.googleapis.com/auth/userinfo.email {SCOPE_DRIVE_FILE}"
        ),
        "id_token": id_token({"email": EMAIL, "sub": "123"}),
    }

    grant = exchange(answering(answer, seen=seen))

    assert grant.access_token == ACCESS
    assert grant.refresh_token == REFRESH
    assert grant.email == EMAIL
    assert grant.holds(SCOPE_DRIVE_FILE)
    sent = form(seen[0])
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "code-1"
    assert sent["redirect_uri"] == "https://example.test/cb/"


def test_a_grant_without_drive_file_says_so() -> None:
    """Google's consent screen lets somebody untick it and press continue."""
    grant = exchange(answering({"access_token": ACCESS, "scope": "openid email"}))

    assert not grant.holds(SCOPE_DRIVE_FILE)


def test_tokens_and_the_email_stay_out_of_repr() -> None:
    answer = {
        "access_token": ACCESS,
        "refresh_token": REFRESH,
        "id_token": id_token({"email": EMAIL}),
    }

    text = repr(exchange(answering(answer)))

    assert ACCESS not in text
    assert REFRESH not in text
    assert EMAIL not in text


@pytest.mark.parametrize("broken", ["", "not-a-jwt", "a.!!!.c", "a.bm90LWpzb24.c"])
def test_an_unreadable_id_token_leaves_the_email_blank(broken: str) -> None:
    grant = exchange(answering({"access_token": ACCESS, "id_token": broken}))

    assert grant.email == ""


def test_a_used_or_expired_code_reads_as_a_lost_grant() -> None:
    """To the person it is the same thing: press the button again."""
    http = answering({"error": "invalid_grant", "error_description": "Bad"}, status=400)

    with pytest.raises(AccessRevoked):
        exchange(http)


def test_our_own_misconfiguration_is_not_blamed_on_the_person() -> None:
    """A wrong client secret must not break every customer's link."""
    http = answering({"error": "invalid_client"}, status=401)

    with pytest.raises(GoogleAPIError) as caught:
        refresh(client_id="cid", client_secret="bad", refresh_token=REFRESH, http=http)

    assert not isinstance(caught.value, AccessRevoked)


def test_refresh_sends_the_refresh_token_and_brings_back_none() -> None:
    seen: list[httpx.Request] = []

    grant = refresh(
        client_id="cid",
        client_secret="secret",
        refresh_token=REFRESH,
        http=answering({"access_token": ACCESS, "expires_in": 3599}, seen=seen),
    )

    assert grant.access_token == ACCESS
    assert grant.refresh_token == ""
    assert form(seen[0])["grant_type"] == "refresh_token"
    assert form(seen[0])["refresh_token"] == REFRESH


def test_a_revoked_refresh_token_is_a_lost_grant() -> None:
    http = answering({"error": "invalid_grant"}, status=400)

    with pytest.raises(AccessRevoked):
        refresh(
            client_id="cid", client_secret="secret", refresh_token=REFRESH, http=http
        )


def test_an_answer_without_an_access_token_is_refused() -> None:
    with pytest.raises(GoogleAPIError):
        refresh(
            client_id="cid",
            client_secret="secret",
            refresh_token=REFRESH,
            http=answering({"expires_in": 10}),
        )


def test_a_token_endpoint_outage_is_temporary() -> None:
    http = answering({"error": "backend_error"}, status=503)

    with pytest.raises(Unavailable):
        refresh(
            client_id="cid", client_secret="secret", refresh_token=REFRESH, http=http
        )


# --- Giving it back --------------------------------------------------------


def test_revoke_posts_the_token() -> None:
    seen: list[httpx.Request] = []

    revoke(token=REFRESH, http=answering(seen=seen))

    assert form(seen[0]) == {"token": REFRESH}


def test_revoking_a_token_that_is_already_gone_is_not_an_error() -> None:
    revoke(token=REFRESH, http=answering({"error": "invalid_token"}, status=400))


def test_revoke_raises_anything_else() -> None:
    with pytest.raises(Unavailable):
        revoke(token=REFRESH, http=answering({"error": "backend_error"}, status=503))
