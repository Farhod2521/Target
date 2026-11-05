"""A refused call takes a Meta connection down only when Meta's own check of
the token agrees, and a connection marked down comes back by itself - with
the leads it held - once Meta calls its token valid again."""

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from adskit.errors import AuthFailed
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from metaads import PROVIDER
from metaads.connection_rows import TokenInfoDTO
from metaads.errors import MetaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import encrypt, fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import PageAccount, ProviderConnection
from app.modules.integrations.services import connect
from app.modules.integrations.services.connect import NO_TOKEN, login_refused
from app.modules.integrations.tasks import heal_connections_task
from app.modules.leads import services as leads
from app.modules.leads.constants import RawEventStatus
from app.modules.leads.models import RawLeadEvent
from app.modules.notifications.services.compose import (
    connection_message,
    reconnected_message,
)
from tests.pg.conftest import sign_up

ALIVE = TokenInfoDTO(user_id="fb-1", is_valid=True)
DEAD = TokenInfoDTO(is_valid=False, error_code=190, error_subcode=460)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


def _meta_says(
    monkeypatch: pytest.MonkeyPatch, answer: TokenInfoDTO | None
) -> list[str]:
    asked: list[str] = []

    def inspect_token(**kwargs: Any) -> TokenInfoDTO:
        asked.append(kwargs["token"])
        if answer is None:
            raise MetaError("Meta did not answer")
        return answer

    monkeypatch.setattr(connect, "inspect_token", inspect_token)
    monkeypatch.setattr(
        connect, "describe_person", lambda **_: SimpleNamespace(name="")
    )
    return asked


def _owner(
    db: Session,
    n: int,
    *,
    status: str = ConnectionStatus.ACTIVE,
    token: bytes | None = None,
) -> tuple[User, ProviderConnection, PageAccount]:
    owner = User(
        email=f"o{n}@example.com", full_name="Ega", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.flush()
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id=f"fb-{n}",
        token_encrypted=encrypt(f"user-{n}") if token is None else token,
        token_fingerprint=fingerprint(f"user-{n}"),
        status=status,
        last_error_code="" if status == ConnectionStatus.ACTIVE else "190",
    )
    db.add(connection)
    db.flush()
    page = PageAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=f"page_{n}",
        connection_id=connection.id,
        name=f"Sahifa {n}",
        token_encrypted=encrypt(f"page-{n}"),
        token_fingerprint=f"p{n}",
        is_active=True,
        is_current=True,
    )
    db.add(page)
    db.commit()
    return owner, connection, page


def _held(db: Session, owner: User, *, hours_ago: float, leadgen: str) -> RawLeadEvent:
    event = RawLeadEvent(
        provider=PROVIDER,
        signature_valid=True,
        page_external_id="page_x",
        leadgen_external_id=leadgen,
        owner_id=owner.id,
        status=RawEventStatus.FAILED,
        error_code="disconnected",
        created_at=utcnow() - timedelta(hours=hours_ago),
    )
    db.add(event)
    db.commit()
    return event


def test_a_refusal_with_a_token_meta_calls_valid_leaves_the_connection_up(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _meta_says(monkeypatch, ALIVE)
    _, connection, _ = _owner(db, 1)

    assert login_refused(db, connection=connection, code="190") is False
    db.refresh(connection)
    assert connection.status == ConnectionStatus.ACTIVE


def test_a_refusal_meta_confirms_marks_the_connection_with_meta_s_reason(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _meta_says(monkeypatch, DEAD)
    _, connection, _ = _owner(db, 1)

    assert login_refused(db, connection=connection, code="190") is True
    db.refresh(connection)
    assert (connection.status, connection.last_error_code) == (
        ConnectionStatus.INVALID,
        "190",
    )


def test_meta_not_answering_never_takes_the_connection_down(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _meta_says(monkeypatch, None)
    _, connection, _ = _owner(db, 1)

    assert login_refused(db, connection=connection, code="190") is False
    db.refresh(connection)
    assert connection.status == ConnectionStatus.ACTIVE


def test_a_lead_refused_with_a_working_token_fails_alone(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _meta_says(monkeypatch, ALIVE)
    _, connection, page = _owner(db, 1)

    def refuse(**_: Any) -> None:
        raise AuthFailed("Error validating access token", code="190")

    monkeypatch.setattr(
        leads.registry,
        "get",
        lambda _: SimpleNamespace(leads=SimpleNamespace(fetch_lead=refuse)),
    )
    event = RawLeadEvent(
        provider=PROVIDER,
        signature_valid=True,
        page_external_id=page.external_id,
        leadgen_external_id="lead-1",
    )
    db.add(event)
    db.commit()

    assert leads.import_lead(db, event_id=str(event.id)) == "failed"
    db.refresh(connection)
    db.refresh(event)
    assert connection.status == ConnectionStatus.ACTIVE
    assert (event.status, event.error_code) == (RawEventStatus.FAILED, "190")


def test_a_connection_meta_calls_valid_again_comes_back_with_its_old_leads(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _meta_says(monkeypatch, ALIVE)
    owner, connection, _ = _owner(db, 1, status=ConnectionStatus.INVALID)
    other, _, _ = _owner(db, 2)
    old = _held(db, owner, hours_ago=24 * 5, leadgen="old")
    _held(db, owner, hours_ago=3, leadgen="new")
    _held(db, owner, hours_ago=24 * 120, leadgen="gone")
    _held(db, other, hours_ago=24 * 5, leadgen="not-theirs")
    sent: list[tuple[str, tuple[object, ...], str]] = []

    from celery import Task

    def apply_async(
        self: Task, args: Any = None, kwargs: Any = None, **options: Any
    ) -> None:
        sent.append((self.name, tuple(args or ()), options.get("queue", self.queue)))

    monkeypatch.setattr(Task, "apply_async", apply_async)
    monkeypatch.setattr("app.modules.integrations.tasks.task_session", _session_of(db))

    assert heal_connections_task.run() == 1

    db.refresh(connection)
    assert (connection.status, connection.last_error_code) == (
        ConnectionStatus.ACTIVE,
        "",
    )
    # The newer one is the retry sweep's; past Meta's 90 days nothing is left.
    # The owner hears of both held leads Meta still keeps.
    assert sent == [
        ("app.modules.leads.tasks.import_lead_task", (str(old.id),), "sync"),
        (
            "app.modules.notifications.tasks.deliver_reconnected_task",
            (str(connection.id), 2),
            "webhooks",
        ),
    ]


def test_a_token_taken_away_on_purpose_is_never_asked_about(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _meta_says(monkeypatch, ALIVE)
    _owner(db, 1, status=ConnectionStatus.REVOKED, token=NO_TOKEN)
    _, dead, _ = _owner(db, 2, status=ConnectionStatus.INVALID)
    monkeypatch.setattr(connect, "inspect_token", _answer_dead(asked))
    monkeypatch.setattr("app.modules.integrations.tasks.task_session", _session_of(db))

    assert heal_connections_task.run() == 0

    db.refresh(dead)
    assert asked == ["user-2"]
    assert dead.status == ConnectionStatus.INVALID


def _answer_dead(asked: list[str]) -> Any:
    def inspect_token(**kwargs: Any) -> TokenInfoDTO:
        asked.append(kwargs["token"])
        return DEAD

    return inspect_token


def _session_of(db: Session) -> Any:
    from contextlib import contextmanager

    @contextmanager
    def session() -> Any:
        yield db

    return session


def test_the_cabinet_says_how_many_leads_a_broken_connection_holds(
    client: TestClient, db: Session
) -> None:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    db.add(
        ProviderConnection(
            owner_id=user.id,
            provider=PROVIDER,
            external_user_id="fb-1",
            token_encrypted=encrypt("user-1"),
            token_fingerprint=fingerprint("user-1"),
            status=ConnectionStatus.INVALID,
        )
    )
    db.commit()
    for n in range(3):
        _held(db, user, hours_ago=n + 1, leadgen=f"l{n}")

    cabinet = client.get("/api/v1/connections/cabinet", headers=auth).json()

    assert cabinet["meta_connection_broken"]["status"] == ConnectionStatus.INVALID
    assert cabinet["meta_held_leads"] == 3


def test_the_bot_names_the_held_leads_and_the_way_back() -> None:
    broken = connection_message(held=319).text
    back = reconnected_message(leads=319).text

    assert "319 ta yangi mijoz arizasi kutib turibdi" in broken
    assert "kutib turibdi" not in connection_message().text
    assert "qayta ishlayapti" in back and "319 ta" in back
