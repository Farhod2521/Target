"""Signing in and up with Google, the role question, and tying Google from
Settings. Google itself is replaced by ``login_profile`` answering a profile."""

from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from googlekit import GoogleAPIError, GoogleProfile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import SocialIdentity, User
from app.modules.accounts.services import social_login
from tests.conftest import SIGNUP, register, signed_in

SITE = "https://targetolog.test"
NEW = GoogleProfile(
    subject="g-1", email="new@gmail.com", email_verified=True, name="Vali Aliyev"
)


@pytest.fixture(autouse=True)
def google_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[GoogleProfile]]:
    monkeypatch.setattr(settings, "site_url", SITE)
    monkeypatch.setattr(settings, "google_login_enabled", True)
    monkeypatch.setattr(settings, "google_oauth_client_id", "cid")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "secret")
    answers: list[GoogleProfile] = [NEW]

    def answer(**_: object) -> GoogleProfile:
        return answers[-1]

    monkeypatch.setattr(social_login, "login_profile", answer)
    yield answers


def press(
    client: TestClient, headers: dict[str, str] | None = None, **body: str
) -> str:
    """The state Google would carry back from the start's address."""
    path = (
        "/api/v1/account/social/google/start"
        if headers
        else "/api/v1/auth/social/google/start"
    )
    started = client.post(path, json=body, headers=headers or {})
    assert started.status_code == 200, started.text
    return str(parse_qs(urlparse(started.json()["url"]).query)["state"][0])


def back(client: TestClient, state: str, **query: str) -> str:
    """Where the callback sends the browser, without the site."""
    answer = client.get(
        "/api/v1/auth/social/google/callback",
        params={"state": state, "code": "c-1"} | query,
        follow_redirects=False,
    )
    assert answer.status_code == 302, answer.text
    location = answer.headers["location"]
    assert location.startswith(SITE)
    return location.removeprefix(SITE)


def token_of(path: str, prefix: str) -> str:
    assert path.startswith(prefix), path
    return path.removeprefix(prefix).strip("/")


def test_the_buttons_are_listed_only_when_switched_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get("/api/v1/auth/social").json() == {"providers": ["google"]}
    monkeypatch.setattr(settings, "google_login_enabled", False)
    assert client.get("/api/v1/auth/social").json() == {"providers": []}
    refused = client.post("/api/v1/auth/social/google/start", json={})
    assert refused.status_code == 404
    assert refused.json()["code"] == "social_unavailable"


def test_the_start_asks_google_for_who_only(client: TestClient) -> None:
    url = client.post("/api/v1/auth/social/google/start", json={}).json()["url"]
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://accounts.google.com/")
    assert query["scope"] == ["openid email profile"]
    assert query["prompt"] == ["select_account"]
    assert query["redirect_uri"] == [f"{SITE}/api/v1/auth/social/google/callback"]
    assert "access_type" not in query and "include_granted_scopes" not in query


def test_somebody_new_gives_phone_and_role_then_signs_in(
    client: TestClient, db: Session
) -> None:
    path = back(client, press(client, next="/app/billing/"))
    token = token_of(path, "/accounts/social/")
    form = client.get(f"/api/v1/auth/social/finish/{token}")
    assert form.json() == {
        "provider": "google",
        "email": "new@gmail.com",
        "full_name": "Vali Aliyev",
        "needs_email": False,
        "phone": "",
    }

    done = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "+998 90 111 22 33", "role": "targetolog"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["next"] == "/app/billing/"
    me = client.get(
        "/api/v1/account",
        headers={"Authorization": f"Bearer {done.json()['access_token']}"},
    ).json()
    assert (me["email"], me["full_name"], me["phone"]) == (
        "new@gmail.com",
        "Vali Aliyev",
        "+998901112233",
    )
    assert (me["role"], me["role_needed"], me["has_password"]) == (
        "targetolog",
        False,
        False,
    )
    user = db.scalar(select(User).where(User.email == "new@gmail.com"))
    assert user is not None and user.password == ""
    # The form is spent; the next press signs straight in.
    assert client.get(f"/api/v1/auth/social/finish/{token}").status_code == 410
    handoff = token_of(back(client, press(client)), "/accounts/handoff/")
    redeemed = client.post(f"/api/v1/auth/handoff/{handoff}")
    assert redeemed.status_code == 200
    assert redeemed.json()["next"] == "/app/"


def test_a_number_another_account_holds_opens_nothing(client: TestClient) -> None:
    register(client)
    token = token_of(back(client, press(client)), "/accounts/social/")
    taken = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": SIGNUP["phone"], "role": "business_owner"},
    )
    assert taken.status_code == 422
    assert taken.json()["code"] == "phone_taken"
    assert "phone" in taken.json()["problems"]
    # The form can be corrected and sent again.
    again = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "+998907776655", "role": "business_owner"},
    )
    assert again.status_code == 200, again.text


def test_the_role_and_phone_are_checked(client: TestClient) -> None:
    token = token_of(back(client, press(client)), "/accounts/social/")
    bad_role = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "+998907776655", "role": "boss"},
    )
    assert bad_role.status_code == 422
    bad_phone = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "123", "role": "agency"},
    )
    assert bad_phone.json()["code"] == "bad_phone"


def test_a_verified_address_we_hold_is_tied_and_signed_in(
    client: TestClient, db: Session, google_on: list[GoogleProfile]
) -> None:
    register(client)
    google_on.append(
        GoogleProfile(subject="g-2", email="ali@example.com", email_verified=True)
    )
    handoff = token_of(back(client, press(client)), "/accounts/handoff/")
    assert client.post(f"/api/v1/auth/handoff/{handoff}").status_code == 200
    identity = db.scalar(select(SocialIdentity))
    user = db.scalar(select(User))
    assert identity is not None and user is not None
    assert (identity.owner_id, identity.subject) == (user.id, "g-2")


def test_an_unverified_address_is_refused(
    client: TestClient, google_on: list[GoogleProfile]
) -> None:
    register(client)
    google_on.append(
        GoogleProfile(subject="g-3", email="ali@example.com", email_verified=False)
    )
    assert back(client, press(client)) == "/accounts/login/?social_error=unverified"


def test_a_blocked_account_is_not_signed_in(
    client: TestClient, db: Session, google_on: list[GoogleProfile]
) -> None:
    register(client)
    user = db.scalar(select(User))
    assert user is not None
    user.is_active = False
    db.commit()
    google_on.append(
        GoogleProfile(subject="g-4", email="ali@example.com", email_verified=True)
    )
    assert back(client, press(client)) == "/accounts/login/?social_error=blocked"
    assert db.scalar(select(SocialIdentity)) is None


def test_a_forged_or_spent_state_and_a_cancel(client: TestClient) -> None:
    assert back(client, "forged") == "/accounts/login/?social_error=expired"
    state = press(client)
    assert back(client, state, code="", error="access_denied") == (
        "/accounts/login/?social_error=cancelled"
    )
    assert back(client, state) == "/accounts/login/?social_error=expired"


def test_google_failing_lands_on_the_login_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(**_: object) -> GoogleProfile:
        raise GoogleAPIError("invalid_grant")

    monkeypatch.setattr(social_login, "login_profile", broken)
    assert back(client, press(client)) == "/accounts/login/?social_error=failed"


def test_settings_ties_a_google_account_of_another_address(
    client: TestClient, db: Session
) -> None:
    headers = signed_in(client)
    assert back(client, press(client, headers)) == "/app/account/?linked=google"
    links = client.get("/api/v1/account/social", headers=headers).json()
    assert links["providers"] == ["google"]
    assert links["has_password"] is True
    assert [(x["provider"], x["email"]) for x in links["linked"]] == [
        ("google", "new@gmail.com")
    ]
    # Now the Google account signs this one in.
    handoff = token_of(back(client, press(client)), "/accounts/handoff/")
    assert client.post(f"/api/v1/auth/handoff/{handoff}").status_code == 200
    assert db.scalar(select(User).where(User.email == "new@gmail.com")) is None


def test_settings_refuses_a_google_account_another_holds(client: TestClient) -> None:
    token = token_of(back(client, press(client)), "/accounts/social/")
    client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "+998907776655", "role": "other"},
    )
    headers = signed_in(client)
    assert back(client, press(client, headers, next="/app/account/settings/")) == (
        "/app/account/settings/?social_error=taken"
    )


def test_the_only_way_in_is_not_unlinked(client: TestClient) -> None:
    token = token_of(back(client, press(client)), "/accounts/social/")
    done = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "+998907776655", "role": "other"},
    ).json()
    headers = {"Authorization": f"Bearer {done['access_token']}"}
    refused = client.delete("/api/v1/account/social/google", headers=headers)
    assert refused.status_code == 409
    assert refused.json()["code"] == "social_last_way"
    # The first password needs no current one; then Google can go.
    changed = client.put(
        "/api/v1/account/password",
        json={"current_password": "", "new_password": "Qovun-Sabzi-2026"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert (
        client.delete("/api/v1/account/social/google", headers=headers).status_code
        == 204
    )
    assert client.get("/api/v1/account/social", headers=headers).json()["linked"] == []


def test_signup_keeps_the_role_and_older_accounts_are_asked_once(
    client: TestClient,
) -> None:
    headers = signed_in(client, role="agency")
    me = client.get("/api/v1/account", headers=headers).json()
    assert (me["role"], me["role_needed"]) == ("agency", False)

    older = signed_in(client, email="old@example.com", phone="+998907776655")
    assert client.get("/api/v1/account", headers=older).json()["role_needed"] is True
    saved = client.put("/api/v1/account/role", json={"role": "marketer"}, headers=older)
    assert (saved.json()["role"], saved.json()["role_needed"]) == ("marketer", False)
    assert (
        client.put(
            "/api/v1/account/role", json={"role": "x"}, headers=older
        ).status_code
        == 422
    )


def test_the_callback_with_google_switched_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = press(client)
    monkeypatch.setattr(settings, "google_login_enabled", False)
    assert back(client, state) == "/accounts/login/?social_error=unavailable"


def test_an_address_opened_while_the_form_was_open(client: TestClient) -> None:
    token = token_of(back(client, press(client)), "/accounts/social/")
    register(client, email="New@Gmail.com", phone="+998907776655")
    taken = client.post(
        f"/api/v1/auth/social/finish/{token}",
        json={"phone": "+998901112233", "role": "other"},
    )
    assert taken.status_code == 409
