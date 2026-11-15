"""A forgotten password by email: the same answer for every address, the
letter only to a signed-up one, and its link replacing the password."""

import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common import mail
from app.modules.accounts.services import mail_password_reset
from tests.conftest import SIGNUP
from tests.pg.conftest import sign_up

ASK = "/api/v1/auth/reset/email"
TASK = "app.modules.accounts.tasks.mail_password_reset_task"
LINK = re.compile(r"/accounts/reset/([^/\s]+)/")
NEW = {"new_password1": "fresh-secret-7", "new_password2": "fresh-secret-7"}


def _asked(queued: list) -> list[tuple[object, ...]]:
    return [args for name, args in queued if name == TASK]


def test_a_signed_up_address_gets_a_link_that_replaces_the_password(
    client: TestClient, db: Session, queued: list
) -> None:
    sign_up(client)

    answer = client.post(ASK, json={"email": SIGNUP["email"]})

    assert answer.status_code == 202, answer.text
    assert _asked(queued) == [(SIGNUP["email"].lower(),)]
    assert mail_password_reset(db, email=SIGNUP["email"].lower()) is True
    (letter,) = mail.outbox
    assert letter.to.lower() == SIGNUP["email"].lower()
    found = LINK.search(letter.text)
    assert found is not None, letter.text
    token = found.group(1)

    target = client.get(f"/api/v1/auth/reset/{token}")
    assert target.status_code == 200, target.text
    saved = client.post(f"/api/v1/auth/reset/{token}", json=NEW)
    assert saved.status_code == 200, saved.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": NEW["new_password1"]},
    )
    assert login.status_code == 200, login.text


def test_an_unknown_address_hears_the_same_and_gets_nothing(
    client: TestClient, db: Session, queued: list
) -> None:
    sign_up(client)
    known = client.post(ASK, json={"email": SIGNUP["email"]})

    unknown = client.post(ASK, json={"email": "nobody@example.com"})

    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert mail_password_reset(db, email="nobody@example.com") is False
    assert mail.outbox == []


def test_one_address_is_mailed_a_few_times_an_hour_at_most(
    client: TestClient, queued: list
) -> None:
    sign_up(client)

    answers = [
        client.post(ASK, json={"email": SIGNUP["email"]}).status_code for _ in range(5)
    ]

    assert answers == [202] * 5
    assert len(_asked(queued)) == 3
