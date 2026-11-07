"""Signing in and up with Telegram: Log In with Telegram's round trip (OpenID
Connect, replaced here by ``login_profile`` answering a person), the email
the finishing form asks for, the verified number it starts from, a bot chat
linked from the cabinet, tying Telegram from Settings, and the Mini App's
passwordless sign-up."""

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import TelegramLogin, TelegramLoginError
from telegramkit import login as telegram_login

from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import SocialIdentity, User
from app.modules.notifications.models import TelegramChat
from tests.conftest import SIGNUP, signed_in

TOKEN = "123:bot-token"
SITE = "https://targetolog.test"
TG_ID = 987_654
CALLBACK = f"{SITE}/api/v1/auth/social/telegram/callback"
VALI = TelegramLogin(
    id=TG_ID, name="Vali Aliyev", username="vali", phone="998901112233"
)


@pytest.fixture(autouse=True)
def bot(monkeypatch: pytest.MonkeyPatch) -> Callable[[TelegramLogin | None], None]:
    monkeypatch.setattr(settings, "site_url", SITE)
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "targetologai_bot")
    monkeypatch.setattr(settings, "telegram_login_enabled", True)
    monkeypatch.setattr(settings, "telegram_login_client_id", "123")
    monkeypatch.setattr(settings, "telegram_login_client_secret", "secret")
    seen: list[dict[str, str]] = []
    person: list[TelegramLogin | None] = [VALI]

    def answer(**kwargs: str) -> TelegramLogin:
        seen.append(kwargs)
        if person[0] is None:
            raise TelegramLoginError("refused")
        return person[0]

    monkeypatch.setattr(telegram_login, "login_profile", answer)

    def as_person(who: TelegramLogin | None) -> None:
        person[0] = who

    as_person.seen = seen  # type: ignore[attr-defined]
    return as_person


def press(client: TestClient, headers: dict[str, str] | None = None) -> str:
    """The state Telegram's address carries, from the start's address."""
    path = (
        "/api/v1/account/social/telegram/start"
        if headers
        else "/api/v1/auth/social/telegram/start"
    )
    started = client.post(path, json={}, headers=headers or {})
    assert started.status_code == 200, started.text
    url = urlparse(started.json()["url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://oauth.telegram.org/auth"
    query = parse_qs(url.query)
    assert query["client_id"] == ["123"] and query["redirect_uri"] == [CALLBACK]
    return query["state"][0]


def back(client: TestClient, state: str, code: str = "c") -> str:
    answer = client.get(
        "/api/v1/auth/social/telegram/callback",
        params={"state": state, "code": code},
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


def test_telegram_is_offered_only_when_switched_on_with_its_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "telegram" in client.get("/api/v1/auth/social").json()["providers"]
    monkeypatch.setattr(settings, "telegram_login_client_secret", "")
    assert "telegram" not in client.get("/api/v1/auth/social").json()["providers"]


def test_the_code_is_traded_with_the_verifier_the_start_kept(
    client: TestClient, bot: Callable[[TelegramLogin | None], None]
) -> None:
    state = press(client)
    back(client, state)
    sent = bot.seen[-1]  # type: ignore[attr-defined]
    assert sent["redirect_uri"] == CALLBACK and len(sent["verifier"]) >= 43


def test_somebody_new_gives_the_email_and_role_the_phone_comes_filled(
    client: TestClient, db: Session
) -> None:
    token = finish_token(back(client, press(client)))
    form = client.get(f"/api/v1/auth/social/finish/{token}").json()
    assert form == {
        "provider": "telegram",
        "email": "",
        "full_name": "Vali Aliyev",
        "needs_email": True,
        "phone": "+998901112233",
    }
    body = {"phone": form["phone"], "role": "targetolog"}
    missing = client.post(f"/api/v1/auth/social/finish/{token}", json=body)
    assert missing.status_code == 422 and "email" in missing.json()["problems"]
    done = client.post(
        f"/api/v1/auth/social/finish/{token}", json=body | {"email": "Vali@Mail.uz"}
    )
    assert done.status_code == 200, done.text
    user = db.scalar(select(User).where(User.email == "vali@mail.uz"))
    assert user is not None and user.password == "" and user.role == "targetolog"
    assert user.phone == "+998901112233"
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
    assert back(client, press(client)).startswith("/accounts/handoff/")


def test_an_address_another_account_holds_is_refused_under_the_email(
    client: TestClient,
) -> None:
    signed_in(client)
    token = finish_token(back(client, press(client)))
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
    handoff = back(client, press(client))
    assert handoff.startswith("/accounts/handoff/")
    token = handoff.removeprefix("/accounts/handoff/").strip("/")
    assert client.post(f"/api/v1/auth/handoff/{token}").status_code == 200
    identity = db.scalar(select(SocialIdentity))
    assert identity is not None and identity.owner_id == owner.id


def test_a_refusal_a_forged_state_and_a_cancel_sign_nobody_in(
    client: TestClient, bot: Callable[[TelegramLogin | None], None]
) -> None:
    assert back(client, "forged-state") == "/accounts/login/?social_error=expired"
    cancelled = client.get(
        "/api/v1/auth/social/telegram/callback",
        params={"state": press(client), "error": "access_denied"},
        follow_redirects=False,
    )
    assert cancelled.headers["location"].endswith("social_error=cancelled")
    bot(None)
    assert back(client, press(client)) == "/accounts/login/?social_error=failed"
    # Telegram's state cannot be spent on Google's callback.
    google = client.get(
        "/api/v1/auth/social/google/callback",
        params={"state": press(client), "code": "c"},
        follow_redirects=False,
    )
    assert google.headers["location"].endswith("social_error=expired")


def test_settings_ties_telegram_and_refuses_one_another_holds(
    client: TestClient,
) -> None:
    headers = signed_in(client)
    assert back(client, press(client, headers)) == "/app/account/?linked=telegram"
    links = client.get("/api/v1/account/social", headers=headers).json()
    assert [(x["provider"], x["email"]) for x in links["linked"]] == [
        ("telegram", "@vali")
    ]
    other = signed_in(client, email="other@example.com", phone="+998901112299")
    assert back(client, press(client, other)) == "/app/account/?social_error=taken"


def test_the_mini_app_opens_a_passwordless_sign_up_and_then_the_cabinet(
    client: TestClient, db: Session
) -> None:
    held = client.post("/api/v1/miniapp/signup", json={"init_data": launch()}).json()
    token = finish_token(held["finish_url"])
    form = client.get(f"/api/v1/auth/social/finish/{token}").json()
    assert form["needs_email"] is True and form["provider"] == "telegram"
    assert form["phone"] == ""
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
