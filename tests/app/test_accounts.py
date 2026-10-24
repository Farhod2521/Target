import base64
import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.models import Event
from app.modules.referrals.models import ReferralBinding, ReferralCode
from tests.conftest import SIGNUP, code_for, register, signed_in


def test_signup_normalises_and_records_an_event(
    client: TestClient, db: Session
) -> None:
    response = register(client)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "Ali@example.com"
    assert body["user"]["phone"] == "+998901234567"
    assert body["access_token"] and body["refresh_token"]
    assert db.scalars(select(Event.name)).all() == ["user.registered"]


def test_the_same_email_twice_is_refused(client: TestClient) -> None:
    register(client)
    again = client.post("/api/v1/auth/signup", json=SIGNUP)

    assert again.status_code == 409
    assert again.json()["code"] == "conflict"


def test_a_bad_phone_is_refused_in_uzbek(client: TestClient) -> None:
    response = client.post("/api/v1/auth/signup", json=SIGNUP | {"phone": "123"})

    assert response.status_code == 422
    assert "Raqam noto'g'ri" in response.json()["detail"]


def test_login_refresh_and_me(client: TestClient) -> None:
    register(client)
    pair = client.post(
        "/api/v1/auth/login",
        json={"email": "Ali@EXAMPLE.com", "password": "secret-123"},
    ).json()

    me = client.get(
        "/api/v1/account", headers={"Authorization": f"Bearer {pair['access_token']}"}
    )
    again = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}
    )
    wrong_kind = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": pair["access_token"]}
    )

    assert me.status_code == 200 and me.json()["full_name"] == "Ali Valiyev"
    assert again.status_code == 200 and again.json()["access_token"]
    assert wrong_kind.status_code == 401


def test_wrong_password_and_missing_token(client: TestClient) -> None:
    register(client)

    wrong = client.post(
        "/api/v1/auth/login", json={"email": SIGNUP["email"], "password": "nope-nope"}
    )

    assert wrong.status_code == 401
    assert client.get("/api/v1/account").status_code == 401
    assert (
        client.get(
            "/api/v1/account", headers={"Authorization": "Bearer junk"}
        ).status_code
        == 401
    )


def test_a_password_saved_by_django_still_signs_in(
    client: TestClient, db: Session
) -> None:
    digest = base64.b64encode(
        hashlib.pbkdf2_hmac("sha256", b"old-pass-1", b"djangosalt", 1000)
    ).decode()
    db.add(
        User(
            email="old@example.com",
            full_name="Eski",
            phone="",
            password=f"pbkdf2_sha256$1000$djangosalt${digest}",
            date_joined=utcnow(),
        )
    )
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "old@example.com", "password": "old-pass-1"},
    )

    assert response.status_code == 200
    db.expire_all()
    stored = db.scalar(select(User.password).where(User.email == "old@example.com"))
    assert stored.startswith("pbkdf2_sha256$1200000$")


def test_profile_phone_password_and_language(client: TestClient) -> None:
    auth = signed_in(client)

    profile = client.put(
        "/api/v1/account",
        json={"full_name": "Ali V.", "phone": "90 765 43 21"},
        headers=auth,
    )
    language = client.put(
        "/api/v1/account/language", json={"language": "ru"}, headers=auth
    )
    bad_current = client.put(
        "/api/v1/account/password",
        json={"current_password": "x", "new_password": "new-secret-1"},
        headers=auth,
    )
    changed = client.put(
        "/api/v1/account/password",
        json={"current_password": "secret-123", "new_password": "new-secret-1"},
        headers=auth,
    )
    relogin = client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": "new-secret-1"},
    )

    assert profile.json()["phone"] == "+998907654321"
    assert language.json()["language"] == "ru"
    assert bad_current.status_code == 400
    assert changed.status_code == 200
    assert relogin.status_code == 200


def test_a_referral_code_binds_the_new_account(client: TestClient, db: Session) -> None:
    signed_in(client, email="host@example.com")
    host = db.scalar(select(User).where(User.email == "host@example.com"))
    now = utcnow()
    db.add(
        ReferralCode(owner_id=host.id, code="AB12CD", created_at=now, updated_at=now)
    )
    db.commit()

    register(client, email="guest@example.com", referral_code=" ab12cd ")

    binding = db.scalar(select(ReferralBinding))
    assert (
        binding is not None
        and binding.referrer_id == host.id
        and binding.code == "AB12CD"
    )
    assert "referral.bound" in db.scalars(select(Event.name)).all()


def test_signup_waits_for_the_emailed_code(client: TestClient, db: Session) -> None:
    from app.common import mail

    started = client.post("/api/v1/auth/signup", json=SIGNUP)

    assert started.status_code == 202, started.text
    assert started.json()["expires_in"] == 180
    assert db.scalar(select(User.id)) is None
    letter = mail.outbox[-1]
    code = code_for(SIGNUP["email"])
    assert letter.to == "Ali@example.com"
    assert "TargetologAI" in letter.subject and code in letter.text
    assert all(f">{digit}</td>" in letter.html for digit in code)
    assert "3 daqiqa" in letter.text


def test_a_wrong_code_counts_down_and_then_locks(client: TestClient) -> None:
    client.post("/api/v1/auth/signup", json=SIGNUP)
    code = code_for(SIGNUP["email"])
    wrong = "00000" if code != "00000" else "11111"

    first = client.post(
        "/api/v1/auth/signup/verify", json={"email": SIGNUP["email"], "code": wrong}
    )
    assert first.status_code == 400 and first.json()["code"] == "code_wrong"
    assert "4 marta" in first.json()["detail"]
    for _ in range(4):
        last = client.post(
            "/api/v1/auth/signup/verify",
            json={"email": SIGNUP["email"], "code": wrong},
        )
    assert last.status_code == 429 and last.json()["code"] == "code_tries_spent"
    right_too_late = client.post(
        "/api/v1/auth/signup/verify", json={"email": SIGNUP["email"], "code": code}
    )
    assert right_too_late.json()["code"] == "code_tries_spent"


def test_the_code_expires_after_three_minutes(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import time

    from app.modules.accounts.services import signup_code

    client.post("/api/v1/auth/signup", json=SIGNUP)
    code = code_for(SIGNUP["email"])
    later = time.time() + 181
    monkeypatch.setattr(signup_code.time, "time", lambda: later)

    answer = client.post(
        "/api/v1/auth/signup/verify", json={"email": SIGNUP["email"], "code": code}
    )
    assert answer.status_code == 400 and answer.json()["code"] == "code_expired"


def test_resend_waits_a_minute_then_sends_a_new_code(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import time

    from app.modules.accounts.services import signup_code

    client.post("/api/v1/auth/signup", json=SIGNUP)
    first = code_for(SIGNUP["email"])
    soon = client.post("/api/v1/auth/signup/resend", json={"email": SIGNUP["email"]})
    assert soon.status_code == 429 and soon.json()["code"] == "resend_too_soon"

    later = time.time() + 61
    monkeypatch.setattr(signup_code.time, "time", lambda: later)
    again = client.post("/api/v1/auth/signup/resend", json={"email": SIGNUP["email"]})
    assert again.status_code == 200, again.text
    second = code_for(SIGNUP["email"])
    if second != first:
        stale = client.post(
            "/api/v1/auth/signup/verify",
            json={"email": SIGNUP["email"], "code": first},
        )
        assert stale.json()["code"] == "code_wrong"
    done = client.post(
        "/api/v1/auth/signup/verify", json={"email": SIGNUP["email"], "code": second}
    )
    assert done.status_code == 201, done.text
