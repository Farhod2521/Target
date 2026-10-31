"""The CRM over HTTP against PostgreSQL: the setup wizard, a closed card, the
seats a manager needs, and what must be refused rather than answered 500."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.billing.models import Plan, Subscription
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    ProviderConnection,
)
from app.modules.leads.models import Lead, LeadForm

CRM = "/api/v1/crm"
PASSWORD = "Xk9$mQ2vLp7w"
LATER = "2030-01-01T10:00:00Z"


def _auth(user: User) -> dict[str, str]:
    token = tokens.issue(subject=str(user.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def _owner(db: Session, *, status: str = "active") -> User:
    """A paid owner with one pair, a launch of ours and three leads from it."""
    now = utcnow()
    owner = User(
        email="crm@example.com", full_name="Ega", password="!", date_joined=now
    )
    db.add(owner)
    db.flush()
    plan = Plan(price=100, max_adsets=10, llm_cost_limit_minor=0)
    db.add(plan)
    db.flush()
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=plan.id,
            status=status,
            started_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=29),
        )
    )
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id="fb-1",
        token_encrypted=b"x",
        token_fingerprint=fingerprint("x"),
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="act_1",
        connection_id=connection.id,
        name="Asosiy",
        currency="USD",
        timezone="Asia/Tashkent",
        may_advertise=True,
        is_active=True,
        is_current=True,
    )
    page = PageAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="page_1",
        connection_id=connection.id,
        name="Sahifa",
        token_encrypted=b"x",
        token_fingerprint="p1",
        is_active=True,
        is_current=True,
    )
    db.add_all([account, page])
    db.flush()
    db.add(PagePair(owner_id=owner.id, page_id=page.id, ad_account_id=account.id))
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            page_id=page.id,
            provider=PROVIDER,
            status="created",
            created_refs={"campaign": "c_1"},
        )
    )
    form = LeadForm(
        owner_id=owner.id, provider=PROVIDER, external_id="f_1", page_id=page.id
    )
    db.add(form)
    db.flush()
    for n in range(3):
        db.add(
            Lead(
                owner_id=owner.id,
                provider=PROVIDER,
                leadgen_id=f"lid{n}",
                form_id=form.id,
                campaign_external_id="c_1",
                ad_external_id="ad_1",
                phone_e164=f"+99890000000{n}",
                full_name=f"lid{n}",
                submitted_at=now - timedelta(hours=2),
                received_at=now - timedelta(hours=2),
            )
        )
    db.commit()
    return owner


def _stages_step(client: TestClient, head: dict[str, str]) -> dict[str, Any]:
    answer = client.post(
        f"{CRM}/setup/1",
        headers=head,
        json={
            "presets": ["new", "working", "won", "lost"],
            "columns": ["new", "working", "won", "lost"],
        },
    )
    assert answer.status_code == 200
    return answer.json()


def _running(client: TestClient, head: dict[str, str]) -> dict[str, Any]:
    """The wizard walked to the end, alone: every lead lands in the first column."""
    _stages_step(client, head)
    assert client.post(f"{CRM}/setup/skip-members", headers=head).status_code == 200
    step = client.post(
        f"{CRM}/setup/3", headers=head, json={"since": "month", "every_ad": True}
    )
    assert step.status_code == 200
    assert client.post(f"{CRM}/setup/4", headers=head, json={}).status_code == 200
    return client.get(CRM, headers=head).json()


def _member(
    client: TestClient, head: dict[str, str], email: str
) -> tuple[dict[str, Any], dict[str, str]]:
    added = client.post(
        f"{CRM}/settings/members",
        headers=head,
        json={"name": email, "email": email, "password": PASSWORD},
    )
    assert added.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return added.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_working_alone_moves_the_wizard_on(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    assert client.post(f"{CRM}/setup/skip-members", headers=head).status_code == 409
    _stages_step(client, head)

    answer = client.post(f"{CRM}/setup/skip-members", headers=head)

    assert answer.status_code == 200
    settings = client.get(f"{CRM}/settings", headers=head).json()
    assert settings["setup"]["step"] == 3
    assert settings["setup"]["distribution"] == "manual"


def test_a_closed_card_takes_no_more_work(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    url = f"{CRM}/cards/{card}"
    assert client.post(f"{url}/win", headers=head, json={"amount": "150"}).is_success

    refused = [
        client.post(f"{url}/win", headers=head, json={"amount": "7"}),
        client.post(f"{url}/note", headers=head, json={"text": "yopiq"}),
        client.post(f"{url}/no-answer", headers=head),
        client.post(f"{url}/due", headers=head, json={"due": LATER}),
        client.post(f"{url}/due/done", headers=head),
        client.post(f"{url}/take", headers=head),
    ]

    assert [r.json().get("code") for r in refused] == ["card_is_closed"] * 6
    view = client.get(url, headers=head).json()
    assert view["card"]["won_amount_minor"] == 15000
    assert view["card"]["attempts"] == 0


def test_a_closed_card_may_still_change_outcome_and_hands(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    url = f"{CRM}/cards/{card}"
    reason = client.get(f"{CRM}/settings", headers=head).json()["reasons"][0]["id"]
    client.post(f"{url}/win", headers=head, json={"amount": "150"})

    lost = client.post(f"{url}/lose", headers=head, json={"reason": reason})
    again = client.post(f"{url}/lose", headers=head, json={"reason": reason})
    won = client.post(f"{url}/win", headers=head, json={"amount": "90"})
    held = client.post(f"{url}/assign", headers=head, json={"assignee": str(owner.id)})

    assert lost.status_code == won.status_code == held.status_code == 200
    assert again.json()["code"] == "card_is_closed"
    assert won.json()["won_amount_minor"] == 9000


def test_seats_are_told_true(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    card = board["columns"][0]["cards"][0]["id"]
    assert client.get(f"{CRM}/settings", headers=head).json()["seat_open"] is True
    first, _ = _member(client, head, "bir@example.com")
    assert client.get(f"{CRM}/settings", headers=head).json()["seat_open"] is False

    second, signed_in = _member(client, head, "ikki@example.com")

    assert first["seated"] is True
    assert second["seated"] is False
    assert client.get(CRM, headers=signed_in).json() == {"detail": {"crm": "seat"}}
    url = f"{CRM}/settings/members/{second['id']}"
    edited = client.put(url, headers=head, json={"name": "Ikki"})
    assert edited.json()["seated"] is False
    reset = client.post(f"{url}/password", headers=head, json={"password": PASSWORD})
    assert reset.json()["seated"] is False
    view = client.get(f"{CRM}/cards/{card}", headers=head).json()
    assert sorted(m["seated"] for m in view["members"]) == [False, True]

    handed = client.post(
        f"{CRM}/cards/{card}/assign",
        headers=head,
        json={"assignee": second["user"]["id"]},
    )

    assert handed.json()["code"] == "member_not_seated"


def test_a_trial_has_no_seat_open(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db, status="trial"))
    _running(client, head)

    assert client.get(f"{CRM}/settings", headers=head).json()["seat_open"] is False


def test_a_manager_is_sent_to_the_board(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    _running(client, head)
    _, signed_in = _member(client, head, "bir@example.com")
    client.post(
        f"{CRM}/password",
        headers=signed_in,
        json={"password": PASSWORD + "1", "again": PASSWORD + "1"},
    )
    board = client.get(CRM, headers=head).json()
    client.post(
        f"{CRM}/cards/{board['columns'][0]['cards'][0]['id']}/assign",
        headers=head,
        json={"assignee": ""},
    )

    nav = client.get(f"{CRM}/nav", headers=signed_in).json()

    assert nav == {"url": "/app/crm/", "attention": 3}


@pytest.mark.parametrize("email", ["notanemail", "", "a@b"])
def test_a_manager_needs_a_real_email(
    client: TestClient, db: Session, email: str
) -> None:
    head = _auth(_owner(db))
    _running(client, head)

    answer = client.post(
        f"{CRM}/settings/members",
        headers=head,
        json={"name": "V", "email": email, "password": PASSWORD},
    )

    assert answer.json()["code"] == "bad_email"


def test_bad_input_is_refused_not_a_crash(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    url = f"{CRM}/cards/{board['columns'][0]['cards'][0]['id']}"

    huge = client.post(f"{url}/win", headers=head, json={"amount": "9" * 40})
    vast = client.post(f"{url}/win", headers=head, json={"amount": "1e999999"})
    naive = client.post(f"{url}/due", headers=head, json={"due": "2030-01-01T10:00:00"})
    nul = client.get(CRM, headers=head, params={"q": "a\x00b"})
    note = client.post(f"{url}/note", headers=head, json={"text": "a\x00b"})
    kpi = client.post(
        f"{CRM}/settings/members",
        headers=head,
        json={
            "name": "V",
            "email": "v@example.com",
            "password": PASSWORD,
            "kpi_fix": "9" * 40,
        },
    )
    banana = client.post(
        f"{CRM}/settings/state", headers=head, json={"state": "banana"}
    )

    assert huge.json()["code"] == vast.json()["code"] == "amount_too_big"
    assert naive.status_code == 422
    assert nul.status_code == 200
    assert note.json()["last_note"] == "ab"
    assert kpi.json()["code"] == "bad_kpi"
    assert banana.status_code == 422
    assert client.get(CRM, headers=head).json()["running"] is True
