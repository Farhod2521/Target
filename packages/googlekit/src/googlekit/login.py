"""Signing a person in with their Google account: who they are, nothing more.

Only ``openid email profile`` is asked - none of them is a sensitive scope,
so the consent screen needs no verification and shows no "unverified app"
warning. No refresh token is asked for: once the person is known, Google
is not called again.

The ID token comes straight from Google's token endpoint over TLS, which
Google's own guide counts as proof enough without checking the signature.
Its audience, issuer and lifetime are still checked: a token minted for
another app must not open an account here.
"""

import time
from typing import Final
from urllib.parse import urlencode

import httpx

from googlekit.errors import GoogleAPIError
from googlekit.models import GoogleProfile
from googlekit.oauth import AUTHORIZE_URL, TOKEN_URL, _claims
from googlekit.transport import call, session

LOGIN_SCOPES: Final = ("openid", "email", "profile")
ISSUERS: Final = frozenset({"https://accounts.google.com", "accounts.google.com"})
# Clocks drift; a token a few seconds past its time is still the one just minted.
CLOCK_SKEW_SECONDS: Final = 300


def login_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Where to send the browser. ``select_account`` lets a person with
    several Google accounts pick one instead of being signed in as whichever
    the browser holds."""
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(LOGIN_SCOPES),
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def login_profile(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    http: httpx.Client | None = None,
    now: float | None = None,
) -> GoogleProfile:
    """Trade the callback's code for the person it signed in."""
    form = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    with session(http) as client:
        payload = call(client, "POST", TOKEN_URL, form=form)
    claims = _claims(str(payload.get("id_token") or ""))
    if not claims:
        raise GoogleAPIError("the token endpoint answered without an ID token")
    if claims.get("aud") != client_id:
        raise GoogleAPIError("the ID token was minted for another app")
    if claims.get("iss") not in ISSUERS:
        raise GoogleAPIError("the ID token was not issued by Google")
    moment = time.time() if now is None else now
    if float(claims.get("exp") or 0) + CLOCK_SKEW_SECONDS < moment:
        raise GoogleAPIError("the ID token has expired")
    subject = str(claims.get("sub") or "")
    if not subject:
        raise GoogleAPIError("the ID token names nobody")
    verified = claims.get("email_verified")
    return GoogleProfile(
        subject=subject,
        email=str(claims.get("email") or "").strip().lower(),
        email_verified=verified is True or verified == "true",
        name=str(claims.get("name") or "").strip(),
    )


__all__ = ["LOGIN_SCOPES", "login_profile", "login_url"]
