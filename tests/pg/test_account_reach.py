"""A reconnect with another Facebook profile leaves the old profile's chosen
account in the cabinet; the login is asked about it and the account is marked
out of reach - and cleared once the login lists it again.

The 2026-11-09 case: "baraka" chosen through one profile, the owner reconnected
with another that holds no role on it, and every launch was refused at its
first write with Meta's developer sentence.
"""

from types import SimpleNamespace

import pytest
from adskit.dto import AccountStateDTO
from adskit.errors import AdAccountUnreachable, TemporaryFailure
from adskit.refs import ExternalRef
from cryptography.fernet import Fernet
from metaads import PROVIDER
from metaads.account_rows import AdAccountDTO
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import encrypt, fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.integrations.schemas import AdAccountOut
from app.modules.integrations.services import reach, sync
from app.modules.integrations.services.reach import check_connection_reach

BARAKA = "act_1001166539663370"
OTHER = "act_823508516004131"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


def _meta(
    monkeypatch: pytest.MonkeyPatch,
    *,
    listed: list[str],
    unreachable: set[str],
    unknown: set[str] = frozenset(),  # type: ignore[assignment]
) -> list[str]:
    """Meta for one login: what it lists, and what a read of each account says."""
    read: list[str] = []

    def read_account(*, account: ExternalRef, token: str) -> AccountStateDTO:
        read.append(account.id)
        if account.id in unreachable:
            raise AdAccountUnreachable("owner has NOT grant", code="200")
        if account.id in unknown:
            raise TemporaryFailure("later")
        return AccountStateDTO(ref=account, standing="active", raw_status="1")

    bundle = SimpleNamespace(campaigns=SimpleNamespace(read_account=read_account))
    monkeypatch.setattr(reach.registry, "get", lambda provider: bundle)
    monkeypatch.setattr(
        sync,
        "list_ad_accounts",
        lambda **_: [AdAccountDTO(id=i, name=i, account_status=1) for i in listed],
    )
    return read


def _cabinet(db: Session) -> tuple[ProviderConnection, AdAccount]:
    owner = User(
        email="o@example.com", full_name="Ega", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.flush()
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id="1410879581126482",
        token_encrypted=encrypt("new-profile"),
        token_fingerprint=fingerprint("new-profile"),
        status=ConnectionStatus.ACTIVE,
    )
    db.add(connection)
    db.flush()
    baraka = AdAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=BARAKA,
        connection_id=connection.id,
        name="baraka",
        is_active=True,
        is_current=True,
    )
    db.add(baraka)
    db.commit()
    return connection, baraka


def test_the_chosen_account_the_new_profile_does_not_list_is_marked(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, baraka = _cabinet(db)
    read = _meta(monkeypatch, listed=[OTHER], unreachable={BARAKA})

    sync.sync_ad_accounts(db, connection_id=connection.id)

    db.refresh(baraka)
    assert baraka.reach_lost_at is not None
    assert read == [BARAKA]
    assert AdAccountOut.model_validate(baraka).is_reachable is False


def test_unlisted_but_readable_is_left_alone(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The list is cut short past a number of businesses; absence proves nothing."""
    connection, baraka = _cabinet(db)
    _meta(monkeypatch, listed=[OTHER], unreachable=set())

    sync.sync_ad_accounts(db, connection_id=connection.id)

    db.refresh(baraka)
    assert baraka.reach_lost_at is None


def test_a_read_that_did_not_answer_marks_nothing(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, baraka = _cabinet(db)
    _meta(monkeypatch, listed=[OTHER], unreachable=set(), unknown={BARAKA})

    sync.sync_ad_accounts(db, connection_id=connection.id)

    db.refresh(baraka)
    assert baraka.reach_lost_at is None


def test_a_read_that_works_again_clears_the_mark(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, baraka = _cabinet(db)
    baraka.reach_lost_at = utcnow()
    db.commit()
    _meta(monkeypatch, listed=[BARAKA, OTHER], unreachable=set())

    sync.sync_ad_accounts(db, connection_id=connection.id)

    db.refresh(baraka)
    assert baraka.reach_lost_at is None
    assert AdAccountOut.model_validate(baraka).is_reachable is True


def test_listed_through_a_business_but_refused_a_read_is_marked(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listing is not reach: only the read decides, so the mark never flaps."""
    connection, baraka = _cabinet(db)
    _meta(monkeypatch, listed=[BARAKA, OTHER], unreachable={BARAKA})

    sync.sync_ad_accounts(db, connection_id=connection.id)
    sync.sync_ad_accounts(db, connection_id=connection.id)

    db.refresh(baraka)
    assert baraka.reach_lost_at is not None


def test_accounts_nobody_chose_are_not_asked_about(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, baraka = _cabinet(db)
    baraka.is_active = False
    baraka.is_current = False
    db.commit()
    read = _meta(monkeypatch, listed=[OTHER], unreachable={BARAKA})

    sync.sync_ad_accounts(db, connection_id=connection.id)

    assert read == []


def test_the_task_after_a_reconnect_marks_and_counts(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, baraka = _cabinet(db)
    _meta(monkeypatch, listed=[], unreachable={BARAKA})

    assert check_connection_reach(db, connection_id=str(connection.id)) == 1

    db.refresh(baraka)
    assert baraka.reach_lost_at is not None


def test_a_reconnect_queues_the_check(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    queued: list[tuple[str, tuple[object, ...]]],
) -> None:
    from app.modules.integrations.services import connect

    connection, _baraka = _cabinet(db)
    connect._check_reach(db, connection=connection)
    db.commit()

    assert (
        "app.modules.integrations.tasks.check_reach_task",
        (str(connection.id),),
    ) in queued
