from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.agent.models import AgentPolicy
from app.modules.billing.models import Subscription
from app.modules.billing.services import start_trial
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    ProviderConnection,
)
from tests.pg.conftest import sign_up

START = "/api/v1/start"


def _cabinet(db: Session, user: User) -> tuple[AdAccount, PageAccount]:
    """A connection with one ad account and one page, both chosen."""
    connection = ProviderConnection(
        owner_id=user.id,
        provider=PROVIDER,
        external_user_id="fb-1",
        token_encrypted=b"x",
        token_fingerprint=fingerprint("x"),
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=user.id,
        provider=PROVIDER,
        external_id="act_1",
        connection_id=connection.id,
        name="Asosiy",
        currency="USD",
        timezone="Asia/Tashkent",
        may_advertise=True,
        is_current=True,
        is_active=True,
    )
    page = PageAccount(
        owner_id=user.id,
        provider=PROVIDER,
        external_id="page_1",
        connection_id=connection.id,
        name="Bahor kafesi",
        token_encrypted=b"x",
        token_fingerprint="p",
        is_current=True,
        is_active=True,
    )
    db.add_all([account, page])
    db.commit()
    return account, page


def _trial(client: TestClient, db: Session) -> tuple[dict[str, str], User]:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    start_trial(db, user=user, now=utcnow())
    db.commit()
    return auth, user


def test_fresh_trial_is_sent_to_connect_and_cannot_finish(
    client: TestClient, db: Session
) -> None:
    auth, _ = _trial(client, db)

    screen = client.get(START, headers=auth)
    assert screen.status_code == 200, screen.text
    body = screen.json()
    assert body["setup"]["blocked_on"] == "connect"
    assert body["setup"]["state"]["connect"] == "current"
    assert body["setup"]["can_finish"] is False
    assert body["next_action"] == "connect"
    assert body["may_connect"] is True
    assert body["account_locked"] is False
    assert body["pick"]["rows"] == [] and body["pick"]["chosen"] is None
    assert body["polling"] is False and body["tries"] == 1
    assert body["gate"] == {
        "setup_pending": True,
        "redirect_to": "/app/start",
        "message": "Boshqa bo'limlar «Yakunlash» bosilgandan keyin ochiladi.",
        "closed": body["gate"]["closed"],
    }
    assert "metrics" in body["gate"]["closed"]

    gate = client.get(f"{START}/gate", headers=auth)
    assert gate.json()["setup_pending"] is True

    refused = client.post(f"{START}/finish", headers=auth)
    assert refused.status_code == 400
    assert refused.json() == {
        "detail": "Hamma qadamlar bajarilmagan. Ro'yxatda ochiq qolgan qadamni "
        "tekshiring.",
        "code": "setup_not_ready",
    }


def test_no_plan_asks_to_renew_and_is_not_gated(
    client: TestClient, db: Session
) -> None:
    auth = sign_up(client)
    body = client.get(START, headers=auth).json()
    assert body["next_action"] == "renew"
    assert body["gate"]["setup_pending"] is False
    assert body["gate"]["message"] == ""


def test_finish_locks_the_pair_and_switches_the_agent_on(
    client: TestClient, db: Session
) -> None:
    auth, user = _trial(client, db)
    account, page = _cabinet(db, user)

    body = client.get(START, headers=auth).json()
    assert body["setup"]["can_finish"] is True
    assert body["setup"]["ready"] is False
    assert body["setup"]["blocked_on"] == "profile"
    assert body["setup"]["page"]["external_id"] == "page_1"
    assert body["next_action"] == "finish"
    chosen = body["pick"]["chosen"]
    assert chosen["page"]["external_id"] == "page_1"
    assert chosen["payer"]["external_id"] == "act_1"
    assert chosen["problems"] == []
    assert chosen["warnings"] == ["no_instagram"]
    assert chosen["paired"] is False
    assert [o["account"]["external_id"] for o in body["pick"]["options"]] == ["act_1"]
    assert body["billing_url"] and body["page_terms_url"]
    # Leads not subscribed yet: the screen keeps asking, at most MAX_POLLS times.
    assert body["setup"]["state"]["leads"] == "waiting"

    done = client.post(f"{START}/finish", headers=auth)
    assert done.status_code == 200, done.text
    finished = done.json()
    assert finished["message"] == "Tayyorgarlik yakunlandi."
    assert finished["account_locked"] is True
    assert finished["gate"]["setup_pending"] is False

    db.expire_all()
    subscription = db.scalar(select(Subscription))
    assert subscription is not None and subscription.setup_completed_at is not None
    policy = db.scalar(select(AgentPolicy).where(AgentPolicy.owner_id == user.id))
    assert policy is not None and policy.is_enabled is True
    pair = db.scalar(select(PagePair))
    assert pair is not None
    assert (pair.page_id, pair.ad_account_id) == (page.id, account.id)

    # A later "no" is not overruled by a second press.
    policy.is_enabled = False
    db.commit()
    again = client.post(f"{START}/finish", headers=auth)
    assert again.status_code == 200, again.text
    db.expire_all()
    assert db.scalar(select(AgentPolicy.is_enabled)) is False


def test_polls_while_leads_are_being_subscribed(
    client: TestClient, db: Session
) -> None:
    auth, user = _trial(client, db)
    _, page = _cabinet(db, user)
    from app.modules.businesses.models import Business

    db.add(
        Business(
            user_id=user.id,
            page_id=page.id,
            name="Bahor",
            category="cafe",
            timezone="Asia/Tashkent",
            country_code="UZ",
        )
    )
    db.commit()

    body = client.get(START, headers=auth).json()
    assert body["setup"]["state"]["leads"] == "current"
    assert body["polling"] is True and body["tries"] == 1

    near = client.get(START, params={"tries": "19"}, headers=auth).json()
    assert near["polling"] is True and near["tries"] == 20
    spent = client.get(START, params={"tries": "999"}, headers=auth).json()
    assert spent["polling"] is False and spent["tries"] == 21
    junk = client.get(START, params={"tries": "x"}, headers=auth).json()
    assert junk["tries"] == 1


def test_dashboard_numbers_carry_the_setup(client: TestClient, db: Session) -> None:
    auth, _ = _trial(client, db)
    numbers = client.get("/api/v1/metrics/numbers", headers=auth)
    assert numbers.status_code == 200, numbers.text
    setup = numbers.json()["setup"]
    assert setup["ready"] is False
    assert (setup["done"], setup["total"]) == (0, 4)
    assert setup["blocked_on"] == "connect"
    assert setup["page"] is None
