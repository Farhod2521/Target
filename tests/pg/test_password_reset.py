"""A forgotten password through the bot: the link sent to a linked chat, the
form behind it, every other device signed out, the phone told."""

import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.services import (
    announce_password_changed,
    handle_update,
)
from app.modules.notifications.services import (
    password_reset as reset_module,
)
from tests.conftest import SIGNUP
from tests.pg.conftest import sign_up
from tests.pg.test_office_telegram import FakeBot, _text, fake  # noqa: F401

LINK = re.compile(r"/accounts/parol/([^/]+)/$")
NEW = {"new_password1": "fresh-secret-7", "new_password2": "fresh-secret-7"}
CHANGED_TASK = "app.modules.notifications.tasks.deliver_password_changed_task"


def _linked(db: Session, chat_id: str = "700") -> User:
    owner = db.scalar(
        select(User).where(func.lower(User.email) == SIGNUP["email"].lower())
    )
    assert owner is not None
    db.add(
        TelegramChat(
            owner_id=owner.id, chat_id=chat_id, is_active=True, linked_at=utcnow()
        )
    )
    db.commit()
    return owner


def _ask(db: Session, fake: FakeBot, chat_id: str = "700") -> dict:  # noqa: F811
    handle_update(db, payload=_text(chat_id, "/start parol"), now=utcnow())
    return fake.calls[-1][1]


def _token(sent: dict) -> str:
    (button,) = sent["buttons"]
    found = LINK.search(button.url)
    assert found is not None, button.url
    return found.group(1)


def test_a_linked_chat_gets_a_link_that_replaces_the_password(
    client: TestClient,
    db: Session,
    fake: FakeBot,  # noqa: F811
    queued: list,
) -> None:
    other_device = sign_up(client)
    owner = _linked(db)

    sent = _ask(db, fake)
    token = _token(sent)
    assert "a***@example.com" in sent["text"].lower()

    checked = client.get(f"/api/v1/auth/reset/{token}")
    assert checked.status_code == 200, checked.text
    assert checked.json() == {"email": owner.email}

    saved = client.post(f"/api/v1/auth/reset/{token}", json=NEW)
    assert saved.status_code == 200, saved.text
    fresh = {"Authorization": f"Bearer {saved.json()['access_token']}"}
    assert client.get("/api/v1/account", headers=fresh).status_code == 200
    assert client.get("/api/v1/account", headers=other_device).status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"email": owner.email, "password": "fresh-secret-7"}
    )
    assert login.status_code == 200
    assert (CHANGED_TASK, (str(owner.id),)) in queued

    # One use: the same link, again, opens nothing.
    again = client.post(f"/api/v1/auth/reset/{token}", json=NEW)
    assert again.status_code == 400
    assert again.json()["code"] == "reset_link_invalid"


def test_every_older_link_dies_once_the_password_moves(
    client: TestClient,
    db: Session,
    fake: FakeBot,  # noqa: F811
) -> None:
    sign_up(client)
    _linked(db)
    first = _token(_ask(db, fake))
    second = _token(_ask(db, fake))

    assert client.post(f"/api/v1/auth/reset/{second}", json=NEW).status_code == 200

    dead = client.get(f"/api/v1/auth/reset/{first}")
    assert dead.status_code == 400
    assert dead.json()["code"] == "reset_link_invalid"


def test_a_refused_new_password_keeps_the_link(
    client: TestClient,
    db: Session,
    fake: FakeBot,  # noqa: F811
) -> None:
    sign_up(client)
    _linked(db)
    token = _token(_ask(db, fake))

    differ = client.post(
        f"/api/v1/auth/reset/{token}",
        json={"new_password1": "fresh-secret-7", "new_password2": "fresh-secret-8"},
    )
    weak = client.post(
        f"/api/v1/auth/reset/{token}",
        json={"new_password1": "12345678", "new_password2": "12345678"},
    )

    assert differ.status_code == 422
    assert "new_password2" in differ.json()["problems"]
    assert weak.status_code == 422
    assert "new_password" in weak.json()["problems"]
    assert client.get(f"/api/v1/auth/reset/{token}").status_code == 200


def test_an_unlinked_or_switched_off_chat_is_sent_to_support(
    client: TestClient,
    db: Session,
    fake: FakeBot,  # noqa: F811
) -> None:
    sign_up(client)
    owner = _linked(db)
    chat = db.scalar(select(TelegramChat).where(TelegramChat.owner_id == owner.id))
    assert chat is not None
    chat.is_active = False
    db.commit()

    for chat_id in ("700", "999"):
        sent = _ask(db, fake, chat_id)
        assert "ulanmagan" in sent["text"]
        assert all(not LINK.search(button.url) for button in sent["buttons"])


def test_the_phone_is_told_the_password_changed(
    client: TestClient,
    db: Session,
    fake: FakeBot,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield fake

    monkeypatch.setattr(reset_module, "bot", opened)
    sign_up(client)
    owner = _linked(db)

    assert announce_password_changed(db, owner=owner, now=utcnow())
    assert "Parolingiz o'zgartirildi" in fake.texts()[-1]


def test_the_sign_in_page_learns_where_the_bot_is(
    client: TestClient,
    fake: FakeBot,  # noqa: F811
) -> None:
    assert client.get("/api/v1/auth/reset").json() == {
        "bot_url": "https://t.me/client_bot?start=parol"
    }
    assert reset_module.reset_bot_link().endswith("start=parol")
