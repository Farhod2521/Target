"""A connection that no longer works is said so, with when and why, and
what was mirrored through it is marked as old instead of drawn as live.

Measured on production, 2026-11-12: thirty accounts stood behind dead
connections with 166 campaigns still drawn as running, the oldest unread
since September, and nothing recorded when or why any connection fell.
"""

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from metaads.connection_rows import TokenInfoDTO
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import encrypt, fingerprint
from app.common.db import utcnow
from app.modules.audit.constants import EventName
from app.modules.audit.models import Event
from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.models import Subscription
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.integrations.selectors import disconnected_of, frozen_accounts
from app.modules.integrations.selectors.watch import frozen_mirror
from app.modules.integrations.services import connect, discover
from app.modules.integrations.services.connect import (
    disconnect_meta,
    heal_connections,
    login_refused,
)
from tests.pg.test_campaigns_contract import _cabinet_with_figures
from tests.pg.test_sweep_accounts import _plan

ALIVE = TokenInfoDTO(user_id="fb-1", is_valid=True)
DEAD = TokenInfoDTO(is_valid=False, error_code=190, error_subcode=460)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


def _meta_says(monkeypatch: pytest.MonkeyPatch, answer: TokenInfoDTO) -> None:
    monkeypatch.setattr(connect, "inspect_token", lambda **_: answer)
    monkeypatch.setattr(
        connect, "describe_person", lambda **_: SimpleNamespace(name="")
    )


def _cabinet(client: TestClient, db: Session) -> tuple[dict[str, str], Any, Any]:
    headers, campaign = _cabinet_with_figures(client, db)
    account = db.get(AdAccount, campaign.ad_account_id)
    assert account is not None
    connection = account.connection
    connection.token_encrypted = encrypt("user-token")
    connection.token_fingerprint = fingerprint("user-token")
    connection.status = ConnectionStatus.ACTIVE
    account.synced_at = utcnow() - timedelta(hours=5)
    db.commit()
    return headers, account, connection


def _events(db: Session, connection: ProviderConnection, name: str) -> list[Event]:
    return list(
        db.scalars(
            select(Event).where(
                Event.name == name, Event.aggregate_id == str(connection.id)
            )
        )
    )


def test_a_fall_is_written_once_with_metas_reason(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, connection = _cabinet(client, db)
    _meta_says(monkeypatch, DEAD)

    assert login_refused(db, connection=connection, code="190") is True
    # The hourly heal asks about a dead connection again; that is no new fall.
    assert heal_connections(db) == []

    found = _events(db, connection, EventName.CONNECTION_LOST)
    assert len(found) == 1
    assert found[0].payload == {
        "provider": "meta",
        "status": "invalid",
        "code": "190",
        "subcode": "460",
    }
    assert connection.status == ConnectionStatus.INVALID


def test_a_connection_that_comes_back_says_so(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, connection = _cabinet(client, db)
    _meta_says(monkeypatch, DEAD)
    login_refused(db, connection=connection, code="190")
    _meta_says(monkeypatch, ALIVE)

    assert [one.id for one in heal_connections(db)] == [connection.id]

    found = _events(db, connection, EventName.CONNECTION_RESTORED)
    assert len(found) == 1
    assert found[0].payload == {"provider": "meta", "was": "invalid", "code": "190"}


def test_a_working_connection_marks_nothing(client: TestClient, db: Session) -> None:
    headers, account, _ = _cabinet(client, db)

    body = client.get("/api/v1/campaigns", headers=headers).json()
    numbers = client.get("/api/v1/metrics/numbers?period=7", headers=headers).json()

    assert body["disconnected"] is None
    assert body["campaigns"][0]["frozenSince"] is None
    assert body["counts"]["frozen"] == 0
    assert numbers["disconnected"] is None
    assert frozen_accounts(db, account_ids=[account.id]) == {}


def test_the_list_says_its_rows_are_as_old_as_the_last_read(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, account, connection = _cabinet(client, db)
    _meta_says(monkeypatch, DEAD)
    login_refused(db, connection=connection, code="190")

    body = client.get("/api/v1/campaigns", headers=headers).json()

    told = body["disconnected"]
    assert told["network"]["id"] == "meta"
    assert told["status"] == "invalid" and told["code"] == "190"
    assert told["lostAt"] is not None
    assert told["lastSyncedAt"] == account.synced_at.isoformat()
    row = body["campaigns"][0]
    # Kept as last read - and said to be only that.
    assert row["status"] == "active"
    assert row["frozenSince"] == account.synced_at.isoformat()
    assert body["counts"]["running"] == 1 and body["counts"]["frozen"] == 1
    assert body["state"] == "not_connected"


def test_the_dashboard_says_its_figures_stopped(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _, connection = _cabinet(client, db)
    _meta_says(monkeypatch, DEAD)
    login_refused(db, connection=connection, code="190")

    response = client.get("/api/v1/metrics/numbers?period=7", headers=headers)

    assert response.status_code == 200, response.text
    told = response.json()["disconnected"]
    assert told["provider"] == "meta" and told["status"] == "invalid"
    assert told["code"] == "190" and told["lost_at"] is not None
    assert told["last_synced_at"] is not None


def test_a_connection_the_owner_took_away_is_dated_too(
    client: TestClient, db: Session
) -> None:
    _, account, _ = _cabinet(client, db)

    disconnect_meta(db, user=account.owner)
    db.commit()

    found = disconnected_of(db, accounts=[account])
    assert found is not None
    assert found.status == "revoked" and found.lost_at is not None
    assert found.last_synced_at == account.synced_at


def test_a_fall_before_events_were_kept_has_no_date_but_is_still_said(
    client: TestClient, db: Session
) -> None:
    _, account, connection = _cabinet(client, db)
    connection.status = ConnectionStatus.INVALID
    connection.last_error_code = "190"
    db.commit()

    found = disconnected_of(db, accounts=[account])

    assert found is not None and found.lost_at is None
    assert found.last_synced_at == account.synced_at
    assert frozen_accounts(db, account_ids=[account.id]) == {
        account.id: account.synced_at
    }


def test_what_runs_behind_dead_connections_is_reported_once_a_day(
    client: TestClient,
    db: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, account, connection = _cabinet(client, db)
    db.add(
        Subscription(
            owner_id=account.owner_id,
            plan_id=_plan(db).id,
            status=SubscriptionStatus.ACTIVE,
            extra_pages=0,
            started_at=utcnow(),
            expires_at=utcnow() + timedelta(days=30),
            note="",
        )
    )
    db.commit()
    assert frozen_mirror(db).accounts == 0
    connection.status = ConnectionStatus.INVALID
    db.commit()

    found = frozen_mirror(db)
    with caplog.at_level("ERROR"):
        first = discover.report_frozen_mirror(db)
        second = discover.report_frozen_mirror(db)

    assert (found.accounts, found.campaigns) == (1, 1)
    assert found.external_ids == (account.external_id,)
    assert first == second == 1
    said = [r for r in caplog.records if "behind dead connections" in r.message]
    assert len(said) == 1
