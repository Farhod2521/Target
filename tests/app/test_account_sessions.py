from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.passwords import make_password
from app.modules.accounts.constants import (
    LOGIN_FAILURES_PER_EMAIL,
    PASSWORD_FAILURES_PER_USER,
)
from app.modules.accounts.models import User
from tests.conftest import SIGNUP, register, signed_in

LOGIN = {"email": SIGNUP["email"], "password": SIGNUP["password"]}
WRONG = LOGIN | {"password": "nope-nope"}


def _bearer(pair: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {pair['access_token']}"}


def test_login_refuses_after_too_many_wrong_passwords(client: TestClient) -> None:
    register(client)
    for _ in range(LOGIN_FAILURES_PER_EMAIL):
        assert client.post("/api/v1/auth/login", json=WRONG).status_code == 401

    # Even the right password: the hash is not paid for once the limit is met.
    refused = client.post("/api/v1/auth/login", json=LOGIN)

    assert refused.status_code == 429
    assert refused.json()["code"] == "too_many_attempts"


def test_a_successful_login_clears_the_accounts_count(client: TestClient) -> None:
    register(client)
    for _ in range(LOGIN_FAILURES_PER_EMAIL - 1):
        client.post("/api/v1/auth/login", json=WRONG)
    assert client.post("/api/v1/auth/login", json=LOGIN).status_code == 200

    for _ in range(LOGIN_FAILURES_PER_EMAIL - 1):
        assert client.post("/api/v1/auth/login", json=WRONG).status_code == 401
    assert client.post("/api/v1/auth/login", json=LOGIN).status_code == 200


def test_the_email_count_ignores_case(client: TestClient) -> None:
    register(client)
    for _ in range(LOGIN_FAILURES_PER_EMAIL):
        client.post("/api/v1/auth/login", json=WRONG | {"email": "ALI@example.com"})

    assert client.post("/api/v1/auth/login", json=LOGIN).status_code == 429


def test_a_changed_password_signs_every_other_device_out(client: TestClient) -> None:
    register(client)
    other = client.post("/api/v1/auth/login", json=LOGIN).json()
    this = client.post("/api/v1/auth/login", json=LOGIN).json()

    changed = client.put(
        "/api/v1/account/password",
        json={"current_password": "secret-123", "new_password": "new-secret-1"},
        headers=_bearer(this),
    )

    assert changed.status_code == 200, changed.text
    fresh = changed.json()
    assert fresh["user"]["email"] == "Ali@example.com"
    assert client.get("/api/v1/account", headers=_bearer(fresh)).status_code == 200
    assert client.get("/api/v1/account", headers=_bearer(other)).status_code == 401
    assert client.get("/api/v1/account", headers=_bearer(this)).status_code == 401
    stale = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": other["refresh_token"]}
    )
    renewed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": fresh["refresh_token"]}
    )
    assert stale.status_code == 401
    assert renewed.status_code == 200


def test_a_weak_new_password_is_refused_on_its_field(client: TestClient) -> None:
    auth = signed_in(client)

    weak = client.put(
        "/api/v1/account/password",
        json={"current_password": "secret-123", "new_password": "12345678"},
        headers=auth,
    )
    like_email = client.put(
        "/api/v1/account/password",
        json={"current_password": "secret-123", "new_password": "ali-12345"},
        headers=auth,
    )

    assert weak.status_code == 422
    assert weak.json()["problems"]["new_password"]
    assert like_email.status_code == 422
    assert client.get("/api/v1/account", headers=auth).status_code == 200


def test_guessing_the_current_password_is_bounded(client: TestClient) -> None:
    auth = signed_in(client)
    wrong = {"current_password": "guess-0000", "new_password": "new-secret-1"}
    for _ in range(PASSWORD_FAILURES_PER_USER):
        response = client.put("/api/v1/account/password", json=wrong, headers=auth)
        assert response.status_code == 400

    right = client.put(
        "/api/v1/account/password",
        json={"current_password": "secret-123", "new_password": "new-secret-1"},
        headers=auth,
    )

    assert right.status_code == 429
    assert right.json()["code"] == "too_many_attempts"


def test_renaming_keeps_the_phone_and_needs_none(
    client: TestClient, db: Session
) -> None:
    auth = signed_in(client)
    renamed = client.put("/api/v1/account", json={"full_name": "Ali V."}, headers=auth)
    assert renamed.status_code == 200
    assert renamed.json()["phone"] == "+998901234567"

    db.add(
        User(
            email="staff-made@example.com",
            full_name="Xodim ochgan",
            phone="",
            password=make_password("secret-123"),
            date_joined=utcnow(),
        )
    )
    db.commit()
    pair = client.post(
        "/api/v1/auth/login",
        json={"email": "staff-made@example.com", "password": "secret-123"},
    ).json()
    no_phone = client.put(
        "/api/v1/account", json={"full_name": "Yangi ism"}, headers=_bearer(pair)
    )

    assert no_phone.status_code == 200, no_phone.text
    assert no_phone.json() | {"full_name": "Yangi ism", "phone": ""} == no_phone.json()


def test_the_handoff_signs_another_browser_in_once(client: TestClient) -> None:
    auth = signed_in(client)

    issued = client.post(
        "/api/v1/auth/handoff", json={"next": "/app/start/"}, headers=auth
    )
    assert issued.status_code == 200, issued.text
    url = issued.json()["url"]
    assert "/accounts/handoff/" in url and url.endswith("/")
    token = url.rstrip("/").rsplit("/", 1)[-1]

    spent = client.post(f"/api/v1/auth/handoff/{token}")
    again = client.post(f"/api/v1/auth/handoff/{token}")

    assert spent.status_code == 200
    assert spent.json()["next"] == "/app/start/"
    me = client.get("/api/v1/account", headers=_bearer(spent.json()))
    assert me.json()["email"] == "Ali@example.com"
    assert again.status_code == 400
    assert again.json()["code"] == "expired"


def test_the_handoff_lands_only_in_the_cabinet(client: TestClient) -> None:
    auth = signed_in(client)
    url = client.post(
        "/api/v1/auth/handoff", json={"next": "https://evil.example/"}, headers=auth
    ).json()["url"]
    token = url.rstrip("/").rsplit("/", 1)[-1]

    assert client.post(f"/api/v1/auth/handoff/{token}").json()["next"] == "/app/"


def test_the_handoff_refuses_a_blocked_account(client: TestClient, db: Session) -> None:
    auth = signed_in(client)
    url = client.post("/api/v1/auth/handoff", json={}, headers=auth).json()["url"]
    token = url.rstrip("/").rsplit("/", 1)[-1]
    user = db.scalar(select(User))
    assert user is not None
    user.is_active = False
    db.commit()

    refused = client.post(f"/api/v1/auth/handoff/{token}")

    assert refused.status_code == 403
    assert refused.json()["code"] == "blocked"
    assert client.post("/api/v1/auth/handoff", json={}).status_code == 401


def test_a_crm_manager_reads_who_it_is_and_nothing_more(
    client: TestClient, db: Session
) -> None:
    register(client)
    owner = db.scalar(select(User))
    assert owner is not None
    db.add(
        User(
            email="menejer@example.com",
            full_name="Menejer Aziz",
            phone="",
            language="ru",
            password=make_password("secret-123"),
            crm_owner_id=owner.id,
            date_joined=utcnow(),
        )
    )
    db.commit()
    auth = _bearer(
        client.post(
            "/api/v1/auth/login",
            json={"email": "menejer@example.com", "password": "secret-123"},
        ).json()
    )

    me = client.get("/api/v1/account", headers=auth)
    write = client.put("/api/v1/account", json={"full_name": "X"}, headers=auth)
    phone = client.put(
        "/api/v1/account/phone", json={"phone": "+998901112233"}, headers=auth
    )

    assert me.status_code == 200
    assert me.json()["full_name"] == "Menejer Aziz"
    assert me.json()["language"] == "ru"
    assert me.json()["crm_owner_id"] == str(owner.id)
    assert write.status_code == 403
    assert phone.status_code == 403
    assert (
        client.get(
            "/api/v1/account", headers=signed_in(client, email="b@example.com")
        ).json()["crm_owner_id"]
        is None
    )
