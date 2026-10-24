"""Signing somebody in to Google, and keeping the permission alive.

Four calls: the consent URL, the code traded for tokens, the refresh
token traded for a fresh access token, and the permission given back.

**Offline, and consent every time.** ``access_type=offline`` is what makes
Google send a refresh token at all. ``prompt=consent`` is what makes it
send one on the *second* connection too: without it, somebody who
disconnects and connects again comes back with an access token that dies
in an hour and nothing to renew it with.

**The email comes from the ID token, not another request.** Google returns
a signed JWT beside the tokens when ``openid email`` is asked for, and the
address is read out of it. The signature is not checked, which is Google's
own guidance for exactly this case: the token arrived on a direct TLS
connection to Google's token endpoint, so there is nobody in between for a
signature to catch.
"""

import base64
import json
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import urlencode

import httpx

from googlekit.errors import GoogleAPIError
from googlekit.models import Grant
from googlekit.transport import call, session

AUTHORIZE_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL: Final = "https://oauth2.googleapis.com/token"
REVOKE_URL: Final = "https://oauth2.googleapis.com/revoke"

# The narrowest file permission Google has: files this app created, and
# nothing else in the person's Drive. Non-sensitive in Google's own
# classification, which is what keeps the app out of the weeks-long
# verification the full ``spreadsheets`` scope would trigger.
SCOPE_DRIVE_FILE: Final = "https://www.googleapis.com/auth/drive.file"

# Who the person is, and the one permission that does anything.
DEFAULT_SCOPES: Final = ("openid", "email", SCOPE_DRIVE_FILE)

# Read and write the person's Google Ads accounts. Sensitive in Google's
# classification: until the app passes verification, only the Cloud
# project's test users can grant it without a warning screen.
SCOPE_ADWORDS: Final = "https://www.googleapis.com/auth/adwords"


def authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    """Where to send the browser.

    ``state`` ties the callback to the session that started it. The caller
    mints it, keeps it in the session and compares on the way back - see
    ``metaads.oauth.authorize_url`` for what happens without it.
    """
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    http: httpx.Client | None = None,
) -> Grant:
    """Trade the callback's code for tokens.

    ``redirect_uri`` must be the same string the consent URL carried. A
    code that was already used, or has expired, answers ``invalid_grant``
    and arrives as :class:`AccessRevoked` - to the person it means the
    same thing: press the button again.
    """
    form = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    with session(http) as client:
        payload = call(client, "POST", TOKEN_URL, form=form)
    return _grant(payload)


def refresh(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    http: httpx.Client | None = None,
) -> Grant:
    """A fresh access token. The refresh token itself does not change."""
    form = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }
    with session(http) as client:
        payload = call(client, "POST", TOKEN_URL, form=form)
    return _grant(payload)


def revoke(*, token: str, http: httpx.Client | None = None) -> None:
    """Give the permission back.

    Revoking the refresh token revokes the whole grant, access tokens
    included. ``invalid_token`` means it was already gone - the outcome
    being asked for - and is not an error.
    """
    with session(http) as client:
        try:
            call(client, "POST", REVOKE_URL, form={"token": token})
        except GoogleAPIError as exc:
            if not str(exc).startswith("invalid_token"):
                raise


def _grant(payload: Mapping[str, Any]) -> Grant:
    """The token endpoint's answer as a :class:`Grant`."""
    access = str(payload.get("access_token") or "")
    if not access:
        raise GoogleAPIError("the token endpoint answered without an access token")
    claims = _claims(str(payload.get("id_token") or ""))
    return Grant(
        access_token=access,
        refresh_token=str(payload.get("refresh_token") or ""),
        expires_in=int(payload.get("expires_in") or 0),
        scopes=tuple(str(payload.get("scope") or "").split()),
        email=str(claims.get("email") or ""),
        subject=str(claims.get("sub") or ""),
    )


def _claims(id_token: str) -> dict[str, Any]:
    """The ID token's claims, or none. See the module note on not verifying."""
    parts = id_token.split(".")
    if len(parts) != 3:
        return {}
    body = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(body))
    except ValueError:
        return {}
    return claims if isinstance(claims, dict) else {}


__all__ = [
    "AUTHORIZE_URL",
    "DEFAULT_SCOPES",
    "REVOKE_URL",
    "SCOPE_ADWORDS",
    "SCOPE_DRIVE_FILE",
    "TOKEN_URL",
    "authorize_url",
    "exchange_code",
    "refresh",
    "revoke",
]
