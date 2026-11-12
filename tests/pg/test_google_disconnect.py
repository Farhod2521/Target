"""Google Ads: letting go of the connection from inside the app."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from googlekit import Unavailable
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import encrypt, fingerprint
from app.modules.accounts.models import User
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import ProviderConnection
from app.modules.integrations.services import connect
from tests.pg.conftest import sign_up

PATH = "/api/v1/connections/google/disconnect"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


def _connected(client: TestClient, db: Session) -> tuple[dict[str, str], User]:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    db.add(
        ProviderConnection(
            owner_id=user.id,
            provider="google",
            external_user_id="g-1",
            scopes=["https://www.googleapis.com/auth/adwords"],
            token_encrypted=encrypt("refresh-1"),
            token_fingerprint=fingerprint("refresh-1"),
            status=ConnectionStatus.ACTIVE,
        )
    )
    db.commit()
    return auth, user


def _connection(db: Session, user: User) -> ProviderConnection:
    db.expire_all()
    row = db.scalar(
        select(ProviderConnection).where(ProviderConnection.owner_id == user.id)
    )
    assert row is not None
    return row


def test_the_permission_is_handed_back_and_the_token_forgotten(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _connected(client, db)
    revoked: list[str] = []
    monkeypatch.setattr(
        connect, "google_revoke", lambda *, token: revoked.append(token)
    )

    answer = client.post(PATH, headers=auth)

    assert answer.status_code == 200, answer.text
    assert revoked == ["refresh-1"]
    row = _connection(db, user)
    assert row.status == ConnectionStatus.REVOKED
    assert row.token_encrypted == b"" and row.token_fingerprint == ""


def test_google_being_away_does_not_keep_the_token(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, user = _connected(client, db)

    def away(*, token: str) -> None:
        raise Unavailable("down")

    monkeypatch.setattr(connect, "google_revoke", away)

    assert client.post(PATH, headers=auth).status_code == 200
    assert _connection(db, user).token_fingerprint == ""


def test_nothing_to_let_go_of_is_said_so(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, _user = _connected(client, db)
    monkeypatch.setattr(connect, "google_revoke", lambda *, token: None)
    assert client.post(PATH, headers=auth).status_code == 200

    again = client.post(PATH, headers=auth)

    assert again.status_code == 400, again.text
    assert "Google Ads" in again.json()["detail"]
