"""Flows that need PostgreSQL: arrays, partial indexes, row locks.

Skipped unless TEST_DATABASE_URL points at an empty database the tests may
own, e.g. ``postgresql+psycopg://t:t@localhost:55432/t``.
"""

import os
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.common.db import Base, get_db, utcnow
from app.main import app
from tests.conftest import SIGNUP

URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture(scope="session")
def pg_engine():  # type: ignore[no-untyped-def]
    if not URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
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


def sign_up(client: TestClient, **extra: str) -> dict[str, str]:
    client.post("/api/v1/auth/signup", json=SIGNUP | extra)
    email = extra.get("email", SIGNUP["email"])
    pair = client.post(
        "/api/v1/auth/login", json={"email": email, "password": SIGNUP["password"]}
    ).json()
    return {"Authorization": f"Bearer {pair['access_token']}"}


def an_hour_ago():  # type: ignore[no-untyped-def]
    return utcnow() - timedelta(hours=1)
