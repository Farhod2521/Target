"""Signing in as a service account: the app itself, not a person.

A service account holds a private key and trades a short signed statement
(a JWT) for an access token. Nobody presses anything, and nothing expires
except the key, so a spreadsheet only the team reads is written this way.
"""

import base64
import binascii
import json
import time
from collections.abc import Mapping
from typing import Any, Final

import httpx
import jwt

from googlekit.errors import GoogleAPIError
from googlekit.oauth import TOKEN_URL
from googlekit.transport import call, session

SCOPE_SPREADSHEETS: Final = "https://www.googleapis.com/auth/spreadsheets"

_JWT_GRANT: Final = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_LIFETIME_SECONDS: Final = 3600


def read_key(text: str) -> dict[str, Any]:
    """The key file Google hands out, given as its JSON or that JSON in base64.

    Base64 is there because a JSON with line breaks inside its private key
    is awkward to keep on one line of an ``.env`` file.
    """
    raw = text.strip()
    if not raw.startswith("{"):
        try:
            raw = base64.b64decode(raw, validate=False).decode()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(
                "the service account key is neither JSON nor base64"
            ) from exc
    try:
        key = json.loads(raw)
    except ValueError as exc:
        raise ValueError("the service account key is not JSON") from exc
    if (
        not isinstance(key, dict)
        or not key.get("client_email")
        or not key.get("private_key")
    ):
        raise ValueError("the service account key has no client_email or private_key")
    return key


def service_token(
    *,
    key: Mapping[str, Any],
    scopes: tuple[str, ...] = (SCOPE_SPREADSHEETS,),
    now: float | None = None,
    http: httpx.Client | None = None,
) -> str:
    """An access token for the service account ``key`` describes."""
    issued = int(time.time() if now is None else now)
    claims = {
        "iss": key["client_email"],
        "scope": " ".join(scopes),
        "aud": key.get("token_uri") or TOKEN_URL,
        "iat": issued,
        "exp": issued + _LIFETIME_SECONDS,
    }
    headers = {"kid": key["private_key_id"]} if key.get("private_key_id") else None
    assertion = jwt.encode(
        claims, key["private_key"], algorithm="RS256", headers=headers
    )
    with session(http) as client:
        answer = call(
            client,
            "POST",
            str(claims["aud"]),
            form={"grant_type": _JWT_GRANT, "assertion": assertion},
        )
    token = answer.get("access_token")
    if not isinstance(token, str) or not token:
        raise GoogleAPIError("Google gave the service account no access token")
    return token


__all__ = ["SCOPE_SPREADSHEETS", "read_key", "service_token"]
