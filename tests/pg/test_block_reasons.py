"""Blocking with a reason: the super admin's list, what the account reads at
sign-in, and the system's suggestions Support decides on."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.common.passwords import make_password
from app.modules.accounts.constants import BlockCode
from app.modules.accounts.models import (
    AccountBlock,
    BlockReason,
    BlockSuggestion,
    User,
)
from app.modules.accounts.services import known_reason
from app.modules.backoffice.constants import Role
from app.modules.integrations.exceptions import IdentityTaken
from app.modules.integrations.models import ProviderConnection
from app.modules.integrations.services.connect import claim_identity
from app.modules.notifications.models import StaffChat, TelegramChat
from app.modules.notifications.services import block_desk
from tests.pg.test_miniapp_link import TOKEN as MINIAPP_TOKEN
from tests.pg.test_miniapp_link import launch
from tests.pg.test_office_actions import _staff
from tests.pg.test_office_telegram import FakeBot

OFFICE = "/api/v1/office"
PASSWORD = "secret-123"


def _account(db: Session, email: str, *, language: str = "uz", **extra: object) -> User:
    user = User(
        email=email,
        full_name=email.split("@")[0],
        password=make_password(PASSWORD),
        language=language,
        date_joined=utcnow(),
        **extra,
    )
    db.add(user)
    db.commit()
    return user


def _login(client: TestClient, email: str, password: str = PASSWORD) -> object:
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


def _reason(db: Session, name: str, **messages: str) -> BlockReason:
    row = BlockReason(name=name, **messages)
    db.add(row)
    db.commit()
    return row


def test_the_account_reads_its_reason_only_when_shown_and_only_with_its_password(
    client: TestClient, db: Session
) -> None:
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    fraud = _reason(db, "Firibgarlik", message_uz="To'lovni bank orqali qaytargansiz.")
    shown = _account(db, "shown@shop.example.com")
    hidden = _account(db, "hidden@shop.example.com", language="ru")

    told = client.post(
        f"{OFFICE}/customers/{shown.id}/block",
        headers=support,
        json={"reason_id": str(fraud.id), "shown_to_user": True, "note": "Chek #12"},
    )
    assert told.status_code == 200, told.text
    quiet = client.post(
        f"{OFFICE}/customers/{hidden.id}/block",
        headers=support,
        json={"reason_id": str(fraud.id), "note": "Chek #13"},
    )
    assert quiet.status_code == 200, quiet.text

    answer = _login(client, "shown@shop.example.com")
    assert answer.status_code == 403
    assert answer.json()["code"] == "account_blocked"
    assert answer.json()["detail"] == (
        "Akkauntingiz bloklangan. Sabab: To'lovni bank orqali qaytargansiz."
    )
    assert "Chek" not in answer.text
    secret = _login(client, "hidden@shop.example.com").json()
    assert secret["code"] == "account_blocked"
    assert secret["detail"].startswith("Ваш аккаунт заблокирован.")
    assert "Firibgar" not in secret["detail"] and "Chek" not in secret["detail"]

    guessed = _login(client, "shown@shop.example.com", password="wrong-one-1")
    assert guessed.status_code == 401 and guessed.json()["code"] == "bad_credentials"

    card = client.get(f"{OFFICE}/customers/{shown.id}", headers=support).json()
    block = card["profile"]["block"]
    assert block["reason"] == {"value": str(fraud.id), "label": "Firibgarlik"}
    assert block["shown_to_user"] is True and block["note"] == "Chek #12"
    assert block["blocked_by"]["email"] == "support@office.test"
    listed = client.get(f"{OFFICE}/customers?state=blocked", headers=support).json()
    assert {
        row["customer"]["email"]: row["block"]["shown_to_user"]
        for row in listed["rows"]
    } == {
        "shown@shop.example.com": True,
        "hidden@shop.example.com": False,
    }

    freed = client.post(
        f"{OFFICE}/customers/{shown.id}/unblock", headers=support, json={"reason": "Ok"}
    )
    assert freed.status_code == 200, freed.text
    assert _login(client, "shown@shop.example.com").status_code == 200
    db.expire_all()
    [row] = db.scalars(select(AccountBlock).where(AccountBlock.owner_id == shown.id))
    assert row.lifted_at is not None and row.lift_note == "Ok"
    again = client.get(f"{OFFICE}/customers/{shown.id}", headers=support).json()
    assert again["profile"]["block"] is None


def test_an_older_body_still_blocks_under_other_and_a_bare_one_is_refused(
    client: TestClient, db: Session
) -> None:
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    shop = _account(db, "shop@shop.example.com")
    archived = _reason(db, "Eski")
    archived.is_archived = True
    db.commit()
    base = f"{OFFICE}/customers/{shop.id}/block"

    bare = client.post(base, headers=support, json={})
    assert bare.status_code == 422 and "reason_id" in bare.json()["problems"]
    gone = client.post(base, headers=support, json={"reason_id": str(archived.id)})
    assert gone.status_code == 400
    unknown = client.post(
        base,
        headers=support,
        json={"reason_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert unknown.status_code == 422

    old = client.post(base, headers=support, json={"reason": "Spam"})
    assert old.status_code == 200, old.text
    db.expire_all()
    block = db.scalar(select(AccountBlock).where(AccountBlock.owner_id == shop.id))
    assert block is not None and block.reason.code == BlockCode.OTHER
    assert block.note == "Spam" and block.shown_to_user is False
    assert (
        _login(client, "shop@shop.example.com")
        .json()["detail"]
        .startswith("Akkauntingiz bloklangan. Batafsil")
    )


def test_a_crm_manager_is_told_the_owner_is_blocked(
    client: TestClient, db: Session
) -> None:
    owner = _account(db, "owner@shop.example.com")
    _account(db, "manager@shop.example.com", crm_owner_id=owner.id)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    client.post(
        f"{OFFICE}/customers/{owner.id}/block", headers=support, json={"reason": "x"}
    )

    refused = _login(client, "manager@shop.example.com")
    assert refused.status_code == 403
    assert refused.json()["detail"].startswith("Kabinet egasining akkaunti bloklangan")


def test_only_the_superuser_keeps_the_list_and_the_systems_reasons_stay(
    client: TestClient, db: Session
) -> None:
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, root = _staff(db, Role.OWNER, email="root@office.test", superuser=True)
    system = known_reason(db, code=BlockCode.META_IDENTITY_REUSED)
    db.commit()
    url = f"{OFFICE}/block-reasons"
    body = {"name": "Spam", "message_uz": "Spam yubordingiz.", "position": 1}

    for headers in (support, owner):
        assert client.post(url, headers=headers, json=body).status_code == 404
        assert (
            client.put(f"{url}/{system.id}", headers=headers, json=body).status_code
            == 404
        )
    made = client.post(url, headers=root, json=body)
    assert made.status_code == 201, made.text
    spam = made.json()["id"]
    twin = client.post(url, headers=root, json={**body, "name": " spam "})
    assert twin.status_code == 422 and "name" in twin.json()["problems"]

    fixed = client.post(f"{url}/{system.id}/archive", headers=root)
    assert fixed.status_code == 400
    reworded = client.put(
        f"{url}/{system.id}",
        headers=root,
        json={"name": system.name, "message_uz": "Yangi so'zlar"},
    )
    assert reworded.status_code == 200, reworded.text
    assert client.post(f"{url}/{spam}/archive", headers=root).status_code == 200

    seen = client.get(url, headers=support).json()
    assert seen["may_edit"] is False
    assert [row["name"] for row in seen["rows"]] == [system.name]
    assert seen["rows"][0]["is_system"] is True
    assert seen["rows"][0]["message_uz"] == "Yangi so'zlar"
    kept = client.get(url, headers=root).json()
    assert kept["may_edit"] is True
    assert {row["name"]: row["is_archived"] for row in kept["rows"]} == {
        system.name: False,
        "Spam": True,
    }
    assert client.post(f"{url}/{spam}/restore", headers=root).status_code == 200


def _holder_and_twin(db: Session) -> tuple[User, User]:
    holder = _account(db, "first@shop.example.com")
    db.add(
        ProviderConnection(
            owner_id=holder.id,
            provider="meta",
            external_user_id="fb-777",
            token_encrypted=b"x",
            status="active",
        )
    )
    twin = _account(db, "second@shop.example.com")
    db.commit()
    return holder, twin


def test_a_reused_facebook_is_refused_and_suggested_never_blocked(
    client: TestClient, db: Session
) -> None:
    holder, twin = _holder_and_twin(db)
    colleague = _account(db, "tester@office.test", is_staff=True)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, finance = _staff(db, Role.FINANCE, email="money@office.test")

    for user in (twin, twin, twin, colleague):
        with pytest.raises(IdentityTaken):
            claim_identity(db, user=user, external_user_id="fb-777")
    db.expire_all()
    assert db.get(User, twin.id).is_active is True  # type: ignore[union-attr]
    assert _login(client, "second@shop.example.com").status_code == 200

    assert client.get(f"{OFFICE}/block-suggestions", headers=finance).status_code == 404
    listed = client.get(f"{OFFICE}/block-suggestions", headers=support).json()
    assert listed["total"] == 1
    [row] = listed["rows"]
    assert row["customer"]["email"] == "second@shop.example.com"
    assert row["times"] == 3
    assert row["reason"]["name"] == "Bitta Facebook bilan ikkinchi kabinet"
    assert row["detail"]["external_user_id"] == "fb-777"
    assert row["detail"]["held_by"]["email"] == "first@shop.example.com"
    waiting = client.get(f"{OFFICE}/dashboard", headers=support).json()["waiting"]
    assert waiting["block_suggestions"] == 1

    blocked = client.post(
        f"{OFFICE}/block-suggestions/{row['id']}/block",
        headers=support,
        json={"shown_to_user": True},
    )
    assert blocked.status_code == 200, blocked.text
    told = _login(client, "second@shop.example.com").json()
    assert told["detail"].startswith("Akkauntingiz bloklangan. Sabab: Bu Facebook")
    db.expire_all()
    suggestion = db.get(BlockSuggestion, uuid.UUID(row["id"]))
    assert suggestion is not None and suggestion.resolution == "blocked"
    assert (
        client.get(f"{OFFICE}/block-suggestions", headers=support).json()["total"] == 0
    )
    assert (
        client.post(
            f"{OFFICE}/block-suggestions/{row['id']}/block", headers=support, json={}
        ).status_code
        == 404
    )
    assert holder.is_active


def test_a_dismissed_suggestion_comes_back_only_on_a_new_refusal(
    client: TestClient, db: Session
) -> None:
    _, twin = _holder_and_twin(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    with pytest.raises(IdentityTaken):
        claim_identity(db, user=twin, external_user_id="fb-777")
    [row] = client.get(f"{OFFICE}/block-suggestions", headers=support).json()["rows"]

    empty = client.post(
        f"{OFFICE}/block-suggestions/{row['id']}/dismiss", headers=support, json={}
    )
    assert empty.status_code == 422
    let_be = client.post(
        f"{OFFICE}/block-suggestions/{row['id']}/dismiss",
        headers=support,
        json={"note": "Egasi bitta odam"},
    )
    assert let_be.status_code == 200, let_be.text
    assert (
        client.get(f"{OFFICE}/block-suggestions", headers=support).json()["total"] == 0
    )

    with pytest.raises(IdentityTaken):
        claim_identity(db, user=twin, external_user_id="fb-777")
    again = client.get(f"{OFFICE}/block-suggestions", headers=support).json()
    assert again["total"] == 1 and again["rows"][0]["times"] == 1


@pytest.fixture
def staff_bot(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    fake = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield fake

    monkeypatch.setattr(block_desk, "staff_bot", opened)
    monkeypatch.setattr(settings, "staff_bot_token", "t")
    monkeypatch.setattr(settings, "staff_bot_webhook_secret", "s")
    monkeypatch.setattr(settings, "staff_bot_username", "office_bot")
    return fake


def test_support_hears_of_a_new_suggestion_once(
    db: Session, staff_bot: FakeBot
) -> None:
    _, twin = _holder_and_twin(db)
    support, _ = _staff(db, Role.SUPPORT, email="support@office.test")
    seller, _ = _staff(db, Role.SALES, email="sales@office.test")
    for who, chat_id in ((support, "601"), (seller, "602")):
        db.add(
            StaffChat(
                owner_id=who.id, chat_id=chat_id, is_active=True, linked_at=utcnow()
            )
        )
    db.commit()
    with pytest.raises(IdentityTaken):
        claim_identity(db, user=twin, external_user_id="fb-777")
    suggestion = db.scalar(select(BlockSuggestion))
    assert suggestion is not None

    assert (
        block_desk.announce_block_suggestion(db, suggestion_id=str(suggestion.id)) == 1
    )
    [(name, fields)] = staff_bot.calls
    assert name == "send_message" and fields["chat_id"] == "601"
    assert "Bloklash tavsiyasi" in fields["text"]
    assert (
        "second@shop.example.com" in fields["text"]
        and "first@shop.example.com" in fields["text"]
    )
    assert f"/ofis/mijozlar/{twin.id}/" in fields["text"]
    assert block_desk.announce_block_suggestion(db, suggestion_id="nope") == 0


def test_the_mini_app_says_the_cabinet_is_blocked(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", MINIAPP_TOKEN)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s")
    monkeypatch.setattr(settings, "telegram_bot_username", "targetolog_bot")
    shop = _account(db, "shop@shop.example.com")
    db.add(
        TelegramChat(
            owner_id=shop.id, chat_id="987654", is_active=True, linked_at=utcnow()
        )
    )
    db.commit()
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    reason = _reason(db, "Spam", message_uz="Spam yubordingiz.")
    client.post(
        f"{OFFICE}/customers/{shop.id}/block",
        headers=support,
        json={"reason_id": str(reason.id), "shown_to_user": True},
    )

    got = client.post("/api/v1/miniapp/auth", json={"init_data": launch()}).json()
    assert got["error"] == "blocked"
    assert got["message"] == "Akkauntingiz bloklangan. Sabab: Spam yubordingiz."
    assert "access_token" not in got
