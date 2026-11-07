"""Signing in and up with Telegram: the Login Widget's signed redirect, the
email the finishing form asks for, a bot chat linked from the cabinet, tying
Telegram from Settings, and the Mini App's passwordless sign-up."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import SocialIdentity, User
from app.modules.notifications.models import TelegramChat
from tests.conftest import SIGNUP, signed_in

TOKEN = "123:bot-token"
SITE = "https://targetolog.test"
TG_ID = 987_654


@pytest.fixture(autouse=True)
def bot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "site_url", SITE)
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "targetologai_bot")
    monkeypatch.setattr(settings, "telegram_login_enabled", True)


def signed(fields: dict[str, str], token: str = TOKEN) -> dict[str, str]:
    """The Login Widget's query, signed as Telegram signs it."""
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hashlib.sha256(token.encode()).digest()
    return fields | {
        "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    }


def widget(telegram_id: int = TG_ID, age: int = 5, **extra: str) -> dict[str, str]:
    return signed(
        {
            "id": str(telegram_id),
            "first_name": "Vali",
            "last_name": "Aliyev",
            "username": "vali",
            "auth_date": str(int(time.time()) - age),
        }
        | extra
    )


def press(client: TestClient, headers: dict[str, str] | None = None) -> str:
    """The state our widget page carries, from the start's address."""
    path = (
        "/api/v1/account/social/telegram/start"
        if headers
        else "/api/v1/auth/social/telegram/start"
    )
    started = client.post(path, json={}, headers=headers or {})
    assert started.status_code == 200, started.text
    url = urlparse(started.json()["url"])
    assert url.path.startswith("/accounts/telegram/")
    state = url.path.removeprefix("/accounts/telegram/").strip("/")
    assert parse_qs(url.query) == {
        "bot": ["targetologai_bot"],
        "to": [f"{SITE}/api/v1/auth/social/telegram/callback/{state}"],
    }
    return state


def back(client: TestClient, state: str, query: dict[str, str]) -> str:
    answer = client.get(
        f"/api/v1/auth/social/telegram/callback/{state}?{urlencode(query)}",
        follow_redirects=False,
    )
    assert answer.status_code == 302, answer.text
    return answer.headers["location"].removeprefix(SITE)


def finish_token(path: str) -> str:
    assert path.startswith("/accounts/social/"), path
    return path.removeprefix("/accounts/social/").strip("/")


def launch(telegram_id: int = TG_ID) -> str:
    """A Mini App's init data, signed with the bot token."""
    fields = {
        "auth_date": str(int(time.time()) - 60),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Vali", "username": "vali"}
        ),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_telegram_is_offered_only_when_switched_on_and_the_bot_is_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "telegram" in client.get("/api/v1/auth/social").json()["providers"]
    monkeypatch.setattr(settings, "telegram_bot_username", "")
    assert "telegram" not in client.get("/api/v1/auth/social").json()["providers"]


def test_somebody_new_gives_the_email_phone_and_role(
    client: TestClient, db: Session
) -> None:
    token = finish_token(back(client, press(client), widget()))
    form = client.get(f"/api/v1/auth/social/finish/{token}").json()
    assert form == {
        "provider": "telegram",
        "email": "",
        "full_name": "Vali Aliyev",
        "needs_email": True,
    }
    body = {"phone": "+998901112233", "role": "targetolog"}
    missing = client.post(f"/api/v1/auth/social/finish/{token}", json=body)
    assert missing.status_code == 422 and "email" in missing.json()["problems"]
    done = client.post(
        f"/api/v1/auth/social/finish/{token}", json=body | {"email": "Vali@Mail.uz"}
    )
    assert done.status_code == 200, done.text
    user = db.scalar(select(User).where(User.email == "vali@mail.uz"))
    assert user is not None and user.password == "" and user.role == "targetolog"
    identity = db.scalar(
        select(SocialIdentity).where(SocialIdentity.owner_id == user.id)
    )
    assert identity is not None
    assert (identity.provider, identity.subject, identity.email) == (
        "telegram",
        str(TG_ID),
        "@vali",
    )
    # The next press signs straight in.
    again = back(client, press(client), widget())
    assert again.startswith("/accounts/handoff/")


def test_an_address_another_account_holds_is_refused_under_the_email(
    client: TestClient,
) -> None:
    signed_in(client)
    token = finish_token(back(client, press(client), widget()))
    taken = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "+998907776655", "role": "other", "email": SIGNUP["email"]},
    )
    assert taken.status_code == 422
    assert taken.json()["code"] == "email_in_use"
    assert "email" in taken.json()["problems"]
    # The form can be corrected and sent again.
    fixed = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "+998907776655", "role": "other", "email": "other@mail.uz"},
    )
    assert fixed.status_code == 200, fixed.text


def test_a_bot_chat_linked_from_the_cabinet_signs_straight_in(
    client: TestClient, db: Session
) -> None:
    signed_in(client)
    owner = db.scalar(select(User))
    assert owner is not None
    db.add(
        TelegramChat(
            owner_id=owner.id, chat_id=str(TG_ID), username="vali", linked_at=utcnow()
        )
    )
    db.commit()
    handoff = back(client, press(client), widget())
    assert handoff.startswith("/accounts/handoff/")
    token = handoff.removeprefix("/accounts/handoff/").strip("/")
    assert client.post(f"/api/v1/auth/handoff/{token}").status_code == 200
    identity = db.scalar(select(SocialIdentity))
    assert identity is not None and identity.owner_id == owner.id


def test_a_forged_or_stale_redirect_signs_nobody_in(client: TestClient) -> None:
    forged = widget() | {"first_name": "Mallory"}
    assert back(client, press(client), forged) == "/accounts/login/?social_error=failed"
    stale = widget(age=3600)
    assert back(client, press(client), stale) == "/accounts/login/?social_error=failed"
    assert (
        back(client, "forged-state", widget())
        == "/accounts/login/?social_error=expired"
    )
    # Telegram's state cannot be spent on Google's callback.
    google = client.get(
        "/api/v1/auth/social/telegram/callback",
        params={"state": press(client), "code": "c"},
        follow_redirects=False,
    )
    assert google.headers["location"].endswith("social_error=expired")


def test_settings_ties_telegram_and_refuses_one_another_holds(
    client: TestClient,
) -> None:
    headers = signed_in(client)
    assert (
        back(client, press(client, headers), widget())
        == "/app/account/?linked=telegram"
    )
    links = client.get("/api/v1/account/social", headers=headers).json()
    assert [(x["provider"], x["email"]) for x in links["linked"]] == [
        ("telegram", "@vali")
    ]
    other = signed_in(client, email="other@example.com", phone="+998901112299")
    assert back(client, press(client, other), widget()) == (
        "/app/account/?social_error=taken"
    )


def test_the_mini_app_opens_a_passwordless_sign_up_and_then_the_cabinet(
    client: TestClient, db: Session
) -> None:
    held = client.post("/api/v1/miniapp/signup", json={"init_data": launch()}).json()
    token = finish_token(held["finish_url"])
    form = client.get(f"/api/v1/auth/social/finish/{token}").json()
    assert form["needs_email"] is True and form["provider"] == "telegram"
    done = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={
            "phone": "+998901112233",
            "role": "agency",
            "email": "vali@mail.uz",
            "full_name": "Vali",
        },
    )
    assert done.status_code == 200, done.text
    # The next launch opens the cabinet and links the bot's chat.
    opened = client.post("/api/v1/miniapp/auth", json={"init_data": launch()}).json()
    assert opened["ok"] is True
    chat = db.scalar(select(TelegramChat).where(TelegramChat.chat_id == str(TG_ID)))
    assert chat is not None and chat.is_active
    # A Telegram a cabinet holds is not signed up twice.
    again = client.post("/api/v1/miniapp/signup", json={"init_data": launch()}).json()
    assert again["error"] == "linked"
