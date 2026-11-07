"""Log In with Telegram: OpenID Connect, as core.telegram.org/bots/telegram-login
describes it (the iframe Login Widget is archived there).

The browser goes to Telegram's ``/auth`` with a PKCE challenge, comes back to
our redirect URI (registered in BotFather -> the bot -> Login Widget ->
Allowed URLs) with a ``code``, and the server trades it, with the Client ID
and Client Secret BotFather shows there, for an ID token.

The ID token comes straight from Telegram's token endpoint over TLS and
authenticated by the client secret, which OpenID Connect Core 3.1.3.7 counts
as proof enough without checking the signature (googlekit.login does the
same). Its audience, issuer and lifetime are still checked: a token minted
for another bot must not open an account here.
"""

import base64
import hashlib
import json
import secrets
import time
from typing import Any, Final
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

AUTHORIZE_URL: Final = "https://oauth.telegram.org/auth"
TOKEN_URL: Final = "https://oauth.telegram.org/token"
ISSUER: Final = "https://oauth.telegram.org"
# ``profile`` names the person, ``phone`` brings the number Telegram verified
# (the person consents on Telegram's screen), ``telegram:bot_access`` lets the
# bot write first.
LOGIN_SCOPES: Final = ("openid", "profile", "phone", "telegram:bot_access")
# Clocks drift; a token a few seconds past its time is still the one just minted.
CLOCK_SKEW_SECONDS: Final = 300
TIMEOUT_SECONDS: Final = 15.0


class TelegramLoginError(Exception):
    """Telegram refused the code, or answered something that names nobody."""


class TelegramLogin(BaseModel):
    """The person Telegram signed in. ``id`` is their Telegram user id, which
    is also their private chat with the bot and a Mini App's ``user.id``."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str = Field(default="", repr=False)
    username: str = ""
    phone: str = Field(default="", repr=False)  # digits, verified by Telegram


def new_verifier() -> str:
    """A PKCE code verifier, kept with the round trip's state."""
    return secrets.token_urlsafe(48)


def login_url(*, client_id: str, redirect_uri: str, state: str, verifier: str) -> str:
    """Where to send the browser."""
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(LOGIN_SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def login_profile(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    verifier: str,
    http: httpx.Client | None = None,
    now: float | None = None,
) -> TelegramLogin:
    """Trade the callback's code for the person it signed in."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    client = http or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = client.post(TOKEN_URL, data=form, auth=(client_id, client_secret))
    except httpx.HTTPError as exc:
        raise TelegramLoginError(
            f"token endpoint unreachable: {type(exc).__name__}"
        ) from None
    finally:
        if http is None:
            client.close()
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200 or not isinstance(payload, dict):
        error = payload.get("error") if isinstance(payload, dict) else ""
        raise TelegramLoginError(
            f"token endpoint refused: {response.status_code} {error or ''}".strip()
        )
    claims = _claims(str(payload.get("id_token") or ""))
    if not claims:
        raise TelegramLoginError("the token endpoint answered without an ID token")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if str(client_id) not in {str(a) for a in audiences}:
        raise TelegramLoginError("the ID token was minted for another bot")
    if claims.get("iss") != ISSUER:
        raise TelegramLoginError("the ID token was not issued by Telegram")
    moment = time.time() if now is None else now
    if float(claims.get("exp") or 0) + CLOCK_SKEW_SECONDS < moment:
        raise TelegramLoginError("the ID token has expired")
    try:
        user_id = int(claims.get("id") or claims.get("sub") or "")
    except ValueError:
        raise TelegramLoginError("the ID token names nobody") from None
    name = (
        str(claims.get("name") or "").strip()
        or " ".join(
            str(claims.get(k) or "").strip() for k in ("given_name", "family_name")
        ).strip()
    )
    verified = claims.get("phone_number_verified")
    phone = str(claims.get("phone_number") or "").strip()
    return TelegramLogin(
        id=user_id,
        name=name,
        username=str(claims.get("preferred_username") or "").lstrip("@"),
        # Telegram's numbers are the accounts' own; only an explicit "no" drops it.
        phone=phone if verified not in (False, "false") else "",
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
    "LOGIN_SCOPES",
    "TelegramLogin",
    "TelegramLoginError",
    "login_profile",
    "login_url",
    "new_verifier",
]
