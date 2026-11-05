"""The bot's «Kabinetga kirish» for a Telegram account no cabinet knows yet:
signed up or in inside the Mini App, the account is tied to that cabinet and
the next launch opens it."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.notifications.models import TelegramChat
from tests.conftest import signed_in

TOKEN = "123:bot-token"


@pytest.fixture(autouse=True)
def bot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "targetolog_bot")


def launch(telegram_id: int = 987_654, token: str = TOKEN) -> str:
    """The init data Telegram hands a Mini App, signed with ``token``."""
    fields = {
        "auth_date": str(int(time.time()) - 60),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": telegram_id, "first_name": "Ali", "username": "ali"}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_a_launch_no_cabinet_knows_is_refused_as_unlinked(client: TestClient) -> None:
    got = client.post("/api/v1/miniapp/auth", json={"init_data": launch()})
    assert got.json()["error"] == "unlinked"


def test_signed_in_inside_telegram_the_account_is_tied_and_opens_next_time(
    client: TestClient, db: Session
) -> None:
    auth = signed_in(client)
    tied = client.post(
        "/api/v1/miniapp/link", json={"init_data": launch()}, headers=auth
    )
    assert tied.status_code == 200, tied.text
    assert tied.json() == {"linked": True}
    chat = db.scalar(select(TelegramChat).where(TelegramChat.chat_id == "987654"))
    assert chat is not None and chat.is_active and chat.username == "ali"

    opened = client.post("/api/v1/miniapp/auth", json={"init_data": launch()}).json()
    assert opened["ok"] is True and opened["access_token"]


def test_a_telegram_of_another_cabinet_is_not_taken(client: TestClient) -> None:
    first = signed_in(client, email="first@example.com")
    assert (
        client.post(
            "/api/v1/miniapp/link", json={"init_data": launch()}, headers=first
        ).status_code
        == 200
    )
    second = signed_in(client, email="second@example.com", phone="+998901112234")
    refused = client.post(
        "/api/v1/miniapp/link", json={"init_data": launch()}, headers=second
    )
    assert refused.status_code == 400
    assert refused.json()["code"] == "chat_taken_by_another"


def test_a_forged_launch_ties_nothing(client: TestClient, db: Session) -> None:
    auth = signed_in(client)
    refused = client.post(
        "/api/v1/miniapp/link",
        json={"init_data": launch(token="999:other-bot")},
        headers=auth,
    )
    assert refused.status_code == 400 and refused.json()["code"] == "invalid"
    assert db.scalar(select(TelegramChat)) is None


def test_a_crm_manager_ties_nothing(client: TestClient, db: Session) -> None:
    auth = signed_in(client)
    user = db.scalar(select(User))
    assert user is not None
    owner = User(email="owner@example.com", password="!", date_joined=user.date_joined)
    db.add(owner)
    db.flush()
    user.crm_owner_id = owner.id
    db.commit()
    got = client.post(
        "/api/v1/miniapp/link", json={"init_data": launch()}, headers=auth
    )
    # A manager reaches the CRM only; the cabinet's Telegram stays the owner's.
    assert got.status_code == 403
    assert db.scalar(select(TelegramChat)) is None
