"""The showcase account: written whole, shown full, kept away from Meta and
from the office's counts, and taken away again without a trace."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import Base, utcnow
from app.modules.accounts.models import User
from app.modules.ads.exceptions import ConnectionUnusable
from app.modules.ads.selectors.sweeps import nightly_swept_accounts
from app.modules.ads.services.access import token_for
from app.modules.agent.selectors.policy import agent_owner_ids, owners_to_diagnose
from app.modules.backoffice.selectors import payments
from app.modules.backoffice.selectors.dashboard import recent_payments
from app.modules.backoffice.selectors.stats import customer_ids
from app.modules.billing.models import Invoice, Plan
from app.modules.boards.triggers import _raise
from app.modules.crm.models import CrmCard, CrmStage
from app.modules.demo import NotADemo, seed, wipe
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.integrations.selectors import broken_meta_connections
from app.modules.integrations.selectors.watch import frozen_mirror
from app.modules.integrations.services.connect import heal_connections
from app.modules.metrics.models import FxRate
from app.modules.notifications.services.admin_stats import _payers

EMAIL, PASSWORD = "demo@example.com", "Namoyish-2026"
V1 = "/api/v1"


def _ground(db: Session) -> None:
    """What production already has: a plan to buy and the bank's rates."""
    db.add(
        Plan(
            code="pro",
            name="Pro",
            price=99_000_000,
            currency="UZS",
            max_adsets=50,
            llm_cost_limit_minor=0,
            crm_seat_price=15_000_000,
        )
    )
    today = localtime(utcnow()).date()
    for back in range(0, 80):
        db.add(
            FxRate(
                day=today - timedelta(days=back),
                currency="USD",
                rate=Decimal("12800"),
            )
        )
    db.commit()


def _seeded(db: Session) -> Any:
    _ground(db)
    made = seed(db, email=EMAIL, password=PASSWORD)
    db.commit()
    return made


def _login(client: TestClient, email: str) -> dict[str, str]:
    answer = client.post(
        f"{V1}/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert answer.status_code == 200, answer.text
    return {"Authorization": f"Bearer {answer.json()['access_token']}"}


def test_the_account_is_written_and_taken_away_whole(db: Session) -> None:
    _seeded(db)
    assert db.scalar(select(func.count(User.id))) == 4
    with pytest.raises(NotADemo):
        wipe(db, email="nobody@example.com")
    wipe(db, email=EMAIL)
    db.commit()
    left = {
        table.name: count
        for table in Base.metadata.sorted_tables
        if table.name not in ("plans", "fx_rates")
        and (count := db.scalar(select(func.count()).select_from(table)))
    }
    assert left == {}


def test_every_screen_reads_it_connected_and_fresh(
    client: TestClient, db: Session, queued: list[tuple[str, tuple[object, ...]]]
) -> None:
    _seeded(db)
    head = _login(client, EMAIL)

    numbers = client.get(f"{V1}/metrics/numbers?period=30", headers=head).json()
    assert numbers["disconnected"] is None
    assert (numbers["is_stale"], numbers["auto_refresh"]) == (False, False)
    assert numbers["setup"]["facts"]["connected"] is True
    listing = client.get(f"{V1}/campaigns?period=30", headers=head).json()
    assert listing["disconnected"] is None
    assert listing["sync"]["stale"] is False
    assert listing["counts"] == {"running": 4, "paused": 1, "all": 5, "frozen": 0}
    assert {row["goal"] for row in listing["campaigns"]} == {"lead", "chat", "click"}
    assert all(
        row["metrics"]["results"]
        for row in listing["campaigns"]
        if row["status"] != "paused"
    )

    # Six figures on top, every one of them a number.
    sales = client.get(f"{V1}/crm/stats?period=30", headers=head).json()["sales"]
    for key in ("spend", "revenue", "roas", "cac", "conversion", "deal_time"):
        assert sales["totals"][key]["value"], key
    assert sales["completeness"]["level"] == "ok"

    # Opening the screens and pressing «Yangilash» queue nothing for Meta.
    queued.clear()
    for path in ("/metrics/numbers/refresh?on_open=true", "/metrics/numbers/refresh"):
        assert client.post(f"{V1}{path}", headers=head).status_code == 200
    assert queued == []


def test_nothing_may_ask_meta_about_it(db: Session) -> None:
    _seeded(db)
    account = db.scalar(select(AdAccount))
    assert account is not None
    with pytest.raises(ConnectionUnusable):
        token_for(ad_account=account)
    now = utcnow()
    assert nightly_swept_accounts(db, now=now) == []
    assert agent_owner_ids(db, now=now) == set()
    assert owners_to_diagnose(db) == []
    # Neither mended nor called broken: it is not a connection to judge.
    assert heal_connections(db) == []
    assert broken_meta_connections(db) == []
    assert frozen_mirror(db).accounts == 0
    assert db.scalar(select(ProviderConnection.status)) == "demo"


def test_the_office_counts_none_of_it(db: Session) -> None:
    _seeded(db)
    owner = db.scalar(select(User).where(User.email == EMAIL))
    assert owner is not None
    now = utcnow()
    assert db.scalar(select(func.count(Invoice.id))) == 4
    assert recent_payments(db) == ()
    assert _payers(db, since=now - timedelta(days=400), until=now) == 0
    assert list(db.scalars(customer_ids())) == []
    found = payments.totals(db, now=now)
    assert (found.earned, found.earned_before, found.earned_count) == ((), (), 0)
    assert payments.invoice_page(db).total == 0
    assert payments.subscription_page(db, now=now).total == 0
    # No rule opens a Support ticket for it.
    assert not _raise(db, owner_id=owner.id, reason="setup_late", ref="x", now=now)


def test_a_manager_signs_in_and_works_the_board(
    client: TestClient, db: Session
) -> None:
    made = _seeded(db)
    head = _login(client, made.manager_emails[0])
    board = client.get(f"{V1}/crm", headers=head).json()
    assert board["running"] and not board["is_owner"]
    waiting = board["columns"][0]["cards"]
    assert waiting, "a fresh lead waits to be taken"
    card = waiting[0]["id"]
    assert client.post(f"{V1}/crm/cards/{card}/take", headers=head).status_code == 200
    sold = client.post(
        f"{V1}/crm/cards/{card}/win", headers=head, json={"amount": "2400000"}
    )
    assert sold.status_code == 200, sold.text
    assert sold.json()["won_amount_minor"] == 240_000_000
    # A manager's login opens the board and nothing else.
    assert client.get(f"{V1}/metrics/numbers", headers=head).status_code == 403


@pytest.mark.parametrize("clock", ["07:00", "09:30", "11:00", "12:30", "23:30"])
def test_a_lead_waits_to_be_taken_whatever_the_hour(db: Session, clock: str) -> None:
    """At these hours every lead of the day had been picked up, and the
    board a visitor opened had nothing in its first column."""
    _ground(db)
    hour, minute = (int(part) for part in clock.split(":"))
    now = utcnow().replace(hour=hour, minute=minute, second=0, microsecond=0)

    seed(db, email=EMAIL, password=PASSWORD, now=now)
    db.commit()

    waiting = db.scalar(
        select(func.count(CrmCard.id))
        .join(CrmStage, CrmStage.id == CrmCard.stage_id)
        .where(
            CrmCard.assignee_id.is_(None),
            CrmCard.closed_at.is_(None),
            CrmStage.kind == "new",
        )
    )
    assert waiting and waiting >= 1


def test_another_account_is_never_deleted(client: TestClient, db: Session) -> None:
    _seeded(db)
    other = User(email="mijoz@example.com", full_name="Mijoz", password="!")
    db.add(other)
    db.commit()
    with pytest.raises(NotADemo):
        wipe(db, email="mijoz@example.com")
    manager = "demo+sotuv1@example.com"
    with pytest.raises(NotADemo):
        wipe(db, email=manager)
    assert db.scalar(select(func.count(User.id))) == 5
