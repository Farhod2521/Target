"""Flows that need PostgreSQL: arrays, partial indexes, row locks.

Skipped unless TEST_DATABASE_URL points at an empty database the tests may
own, e.g. ``postgresql+psycopg://t:t@localhost:55432/t``.
"""

import os
import re
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.common.db import Base, get_db, utcnow
from app.main import app
from tests.conftest import SIGNUP, register

URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")


def django_foreign_keys(engine) -> None:  # type: ignore[no-untyped-def]
    """Every foreign key the way Django built production's: NO ACTION, checked
    at commit. ``create_all`` would follow the models' CASCADE and SET NULL,
    which that database never had, and hide every delete that forgets the
    rows pointing at it."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
                "FROM pg_constraint WHERE contype = 'f'"
            )
        ).all()
        for table, name, definition in rows:
            plain = re.sub(
                r"\s+(ON (DELETE|UPDATE) (SET NULL|SET DEFAULT|NO ACTION|CASCADE|"
                r"RESTRICT)|(NOT )?DEFERRABLE|INITIALLY (DEFERRED|IMMEDIATE))",
                "",
                definition,
            )
            conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
            conn.execute(
                text(
                    f'ALTER TABLE {table} ADD CONSTRAINT "{name}" {plain} '
                    "DEFERRABLE INITIALLY DEFERRED"
                )
            )


@pytest.fixture(scope="session")
def pg_engine():  # type: ignore[no-untyped-def]
    if not URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    django_foreign_keys(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_factory(pg_engine) -> Iterator[sessionmaker[Session]]:  # type: ignore[no-untyped-def]
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield sessionmaker(bind=pg_engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
def db(pg_factory: sessionmaker[Session]) -> Iterator[Session]:
    with pg_factory() as session:
        yield session


@pytest.fixture
def client(pg_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with pg_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[object, ...]]]:
    """Celery tasks the flow sent, kept here instead of going to a broker."""
    from celery import Task

    sent: list[tuple[str, tuple[object, ...]]] = []

    def apply_async(self, args=None, kwargs=None, **options):  # type: ignore[no-untyped-def]
        sent.append((self.name, tuple(args or ())))

    monkeypatch.setattr(Task, "apply_async", apply_async)
    return sent


def sign_up(client: TestClient, **extra: str) -> dict[str, str]:
    register(client, **extra)
    email = extra.get("email", SIGNUP["email"])
    pair = client.post(
        "/api/v1/auth/login", json={"email": email, "password": SIGNUP["password"]}
    ).json()
    return {"Authorization": f"Bearer {pair['access_token']}"}


def an_hour_ago():  # type: ignore[no-untyped-def]
    return utcnow() - timedelta(hours=1)


@pytest.fixture(autouse=True)
def ad_providers() -> None:
    """The ad adapters, put back if a package test cleared the registry.

    ``app.bootstrap`` registers them once per process; ``adskit``'s own
    tests clear the registry to test it, and a later flow here would find
    it empty.
    """
    from adskit import registry
    from adskit.errors import ProviderNotRegistered
    from googleadskit import PROVIDER as GOOGLE
    from googleadskit.adapter import bundle as google_bundle
    from metaads import PROVIDER as META
    from metaads.adapter import bundle as meta_bundle

    from app.common.config import settings

    wanted = {
        META: lambda: meta_bundle(
            app_id=settings.meta_app_id, app_secret=settings.meta_app_secret
        ),
        GOOGLE: lambda: google_bundle(
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            rehearse_writes=settings.google_ads_dry_run,
        ),
    }
    for name, build in wanted.items():
        try:
            registry.get(name)
        except ProviderNotRegistered:
            registry.register(name, build())
