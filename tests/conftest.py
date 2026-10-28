import os
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("EMAIL_BACKEND", "memory")
# The Redis cache has no clear(): its login throttle would carry over from one
# test, and one run, to the next until every sign-in was refused.
os.environ.setdefault("CACHE_BACKEND", "memory")

from app.common import mail
from app.common.cache import cache
from app.common.config import settings
from app.common.db import Base, get_db
from app.main import app

TABLES = [
    "users",
    "events",
    "referral_codes",
    "referral_access",
    "referral_bindings",
    "consult_requests",
]


@pytest.fixture(autouse=True)
def fresh_mail_and_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with no letters sent and nothing cached."""
    monkeypatch.setattr(settings, "email_backend", "memory")
    mail.outbox.clear()
    clear = getattr(cache, "clear", None)
    if clear is not None:
        clear()
    yield
    mail.outbox.clear()


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


def code_for(email: str) -> str:
    """The code in the last letter sent to ``email``."""
    from app.modules.accounts.phone import normalize_email

    wanted = normalize_email(email)
    letter = next(m for m in reversed(mail.outbox) if m.to == wanted)
    found = re.match(r"(\d{5})", letter.subject)
    assert found is not None, letter.text
    return found.group(1)


def register(client: TestClient, **extra: str):  # type: ignore[no-untyped-def]
    """Sign up the way a person does: the form, then the emailed code."""
    payload = SIGNUP | extra
    started = client.post("/api/v1/auth/signup", json=payload)
    if started.status_code != 202:
        return started
    return client.post(
        "/api/v1/auth/signup/verify",
        json={"email": payload["email"], "code": code_for(payload["email"])},
    )


def signed_in(client: TestClient, **extra: str) -> dict[str, str]:
    register(client, **extra)
    email = extra.get("email", SIGNUP["email"])
    pair = client.post(
        "/api/v1/auth/login", json={"email": email, "password": SIGNUP["password"]}
    ).json()
    return {"Authorization": f"Bearer {pair['access_token']}"}
