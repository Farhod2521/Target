"""Which accounts the half-hourly and nightly reads visit, and how long a
queued read stays worth running.

Measured on production, 2026-11-12: forty-six connections were dead and
every one of their accounts was still queued each half hour, to end
"unusable" without asking Meta anything; and behind a slow queue the same
account's reads piled up and ran one after another.
"""

from datetime import timedelta
from typing import Any

import pytest
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import tasks as ads_tasks
from app.modules.ads.constants import SWEEP_EXPIRES_SECONDS
from app.modules.ads.selectors import (
    frequently_swept_account_ids,
    nightly_due_account_ids,
    nightly_swept_account_ids,
)
from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.models import Plan, Subscription
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.metrics import tasks as metrics_tasks


def _plan(db: Session) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.code == "standart"))
    if plan is None:
        plan = Plan(
            code="standart",
            name="Standart",
            price=490000,
            currency="UZS",
            period_days=30,
            max_adsets=10,
            llm_cost_limit_minor=1000,
        )
        db.add(plan)
        db.flush()
    return plan


def _account(db: Session, n: int, *, status: str) -> AdAccount:
    owner = User(
        email=f"sweep{n}@example.com",
        full_name="Ega",
        password="!",
        date_joined=utcnow(),
    )
    db.add(owner)
    db.flush()
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id=f"fb-sweep-{n}",
        token_encrypted=b"x",
        token_fingerprint=f"s{n}",
        status=status,
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=f"act_sweep_{n}",
        connection_id=connection.id,
        name=f"Akkaunt {n}",
        timezone="UTC",
        is_active=True,
        is_current=True,
    )
    db.add(account)
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=_plan(db).id,
            status=SubscriptionStatus.ACTIVE,
            extra_pages=0,
            started_at=utcnow(),
            expires_at=utcnow() + timedelta(days=30),
            note="",
        )
    )
    db.commit()
    return account


def test_an_account_behind_a_dead_connection_is_not_queued(db: Session) -> None:
    alive = _account(db, 1, status=ConnectionStatus.ACTIVE)
    _account(db, 2, status=ConnectionStatus.INVALID)
    _account(db, 3, status=ConnectionStatus.REVOKED)
    now = utcnow()

    assert frequently_swept_account_ids(db, now=now) == [alive.id]
    assert nightly_swept_account_ids(db) == [alive.id]
    assert nightly_due_account_ids(db, now=now, hour=now.hour) == [alive.id]


def test_a_connection_put_back_brings_its_accounts_back(db: Session) -> None:
    account = _account(db, 4, status=ConnectionStatus.INVALID)
    assert frequently_swept_account_ids(db, now=utcnow()) == []

    account.connection.status = ConnectionStatus.ACTIVE
    db.commit()

    assert frequently_swept_account_ids(db, now=utcnow()) == [account.id]


def _sent(monkeypatch: pytest.MonkeyPatch, task: Any) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def apply_async(args: Any = None, kwargs: Any = None, **options: Any) -> None:
        sent.append({"args": args, "kwargs": kwargs, **options})

    monkeypatch.setattr(task, "apply_async", apply_async)
    return sent


def _session_of(db: Session) -> Any:
    from contextlib import contextmanager

    @contextmanager
    def session() -> Any:
        yield db

    return session


def test_a_half_hourly_read_left_in_the_queue_is_dropped_before_the_next(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account(db, 5, status=ConnectionStatus.ACTIVE)
    monkeypatch.setattr(ads_tasks, "task_session", _session_of(db))
    monkeypatch.setattr(metrics_tasks, "task_session", _session_of(db))
    mirror = _sent(monkeypatch, ads_tasks.sync_ad_account_task)
    today = _sent(monkeypatch, metrics_tasks.sync_today_task)

    ads_tasks.sync_all_accounts()
    metrics_tasks.sync_today_metrics()

    expected = {"args": (str(account.id),), "expires": SWEEP_EXPIRES_SECONDS}
    # The mirror's half-hourly read may be a light one; the night's is whole.
    assert mirror == [{**expected, "kwargs": {"whole": False}}]
    assert today == [{**expected, "kwargs": None}]
    # Shorter than the half hour between two sweeps, or nothing is dropped.
    assert SWEEP_EXPIRES_SECONDS < 30 * 60
