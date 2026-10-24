from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.common.db import Base, get_db
from app.main import app

TABLES = ["users", "events", "referral_codes", "referral_access", "referral_bindings", "consult_requests"]


@pytest.fixture
def db_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in TABLES])
    yield sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    engine.dispose()


@pytest.fixture
def db(db_factory: sessionmaker[Session]) -> Iterator[Session]:
    with db_factory() as session:
        yield session


@pytest.fixture
def client(db_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with db_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


SIGNUP = {
    "email": "Ali@Example.COM",
    "full_name": "Ali Valiyev",
    "password": "secret-123",
    "phone": "+998901234567",
}


def signed_in(client: TestClient, **extra: str) -> dict[str, str]:
    client.post("/api/v1/auth/signup", json=SIGNUP | extra)
    email = extra.get("email", SIGNUP["email"])
    pair = client.post(
        "/api/v1/auth/login", json={"email": email, "password": SIGNUP["password"]}
    ).json()
    return {"Authorization": f"Bearer {pair['access_token']}"}
