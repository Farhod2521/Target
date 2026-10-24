"""Signing somebody in to Google, and keeping the permission alive."""

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

SCOPE_DRIVE_FILE: Final = "https://www.googleapis.com/auth/drive.file"

DEFAULT_SCOPES: Final = ("openid", "email", SCOPE_DRIVE_FILE)

SCOPE_ADWORDS: Final = "https://www.googleapis.com/auth/adwords"


def authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    """Where to send the browser."""
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
    """Trade the callback's code for tokens."""
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
    """Give the permission back."""
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
