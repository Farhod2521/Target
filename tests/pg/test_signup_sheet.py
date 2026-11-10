"""Sign-ups who did not pay in five minutes, sent to the sheet's Apps Script.

The script is an httpx.MockTransport that answers the way a deployed web
app does: a redirect to the script's output, then that output.
"""

import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.sales.models import SignupSheetRow
from app.modules.sales.services import signup_sheet
from app.modules.sales.services.signup_sheet import (
    HEADINGS,
    LOCK_KEY,
    STARTS_AT,
    ZONE,
    sweep_signup_sheet,
)

URL = "https://script.google.com/macros/s/abc/exec?token=sir"
ECHO = "https://script.googleusercontent.com/macros/echo?user_content_key=k"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=ZONE)


class FakeScript:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.answer = "ok"
        self.status = 200
        self.calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if request.method == "POST":
            assert str(request.url) == URL
            if self.status != 200:
                return httpx.Response(self.status, text="later")
            if self.answer == "ok":
                self.bodies.append(json.loads(request.content))
            return httpx.Response(302, headers={"Location": ECHO})
        assert str(request.url) == ECHO
        return httpx.Response(200, text=self.answer)

    @property
    def rows(self) -> list[list[str]]:
        return [row for body in self.bodies for row in body["rows"]]


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> FakeScript:
    fake = FakeScript()
    real = httpx.Client

    def client(**options: Any) -> httpx.Client:
        return real(transport=httpx.MockTransport(fake.handle), **options)

    monkeypatch.setattr(signup_sheet.httpx, "Client", client)
    monkeypatch.setattr(settings, "signup_sheet_url", URL)
    cache.delete(LOCK_KEY)
    return fake


def _user(db: Session, email: str, joined: datetime, **fields: Any) -> User:
    user = User(
        email=email,
        full_name=fields.pop("full_name", email.split("@")[0]),
        phone=fields.pop("phone", "+998901234567"),
        password="!",
        date_joined=joined,
        **fields,
    )
    db.add(user)
    db.flush()
    return user


def _plan(db: Session) -> Plan:
    plan = Plan(price=100, max_adsets=10, llm_cost_limit_minor=0)
    db.add(plan)
    db.flush()
    return plan


def _paid(
    db: Session, user: User, plan: Plan, status: str = InvoiceStatus.PAID
) -> None:
    db.add(
        Invoice(
            owner_id=user.id,
            number=f"TA-{user.email[:6]}",
            plan_id=plan.id,
            amount_minor=49_000_000,
            currency="UZS",
            period_days=30,
            expires_at=NOW + timedelta(days=1),
            status=status,
            paid_at=NOW if status == InvoiceStatus.PAID else None,
        )
    )


def _emails(script: FakeScript) -> list[str]:
    return [row[3] for row in script.rows]


def test_unpaid_owners_from_the_start_date_are_sent_once(
    db: Session, script: FakeScript
) -> None:
    plan = _plan(db)
    owner = _user(
        db,
        "ali@shop.test",
        NOW - timedelta(minutes=30),
        full_name="Ali Valiyev",
        phone="+998901112233",
        role="business_owner",
    )
    _user(db, "early@shop.test", STARTS_AT + timedelta(minutes=1))
    _user(db, "yesterday@shop.test", STARTS_AT - timedelta(seconds=1))
    _user(db, "fresh@shop.test", NOW - timedelta(minutes=3))
    payer = _user(db, "payer@shop.test", NOW - timedelta(minutes=20))
    _paid(db, payer, plan)
    waiting = _user(db, "held@shop.test", NOW - timedelta(minutes=20))
    _paid(db, waiting, plan, status=InvoiceStatus.HELD)
    given = _user(db, "given@shop.test", NOW - timedelta(minutes=20))
    db.add(
        Subscription(
            owner_id=given.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            started_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )
    )
    _user(db, "manager@shop.test", NOW - timedelta(hours=1), crm_owner_id=owner.id)
    _user(db, "staff@shop.test", NOW - timedelta(hours=1), is_staff=True)
    _user(db, "blocked@shop.test", NOW - timedelta(hours=1), is_active=False)
    db.commit()

    assert sweep_signup_sheet(db, now=NOW) == 3

    assert script.bodies[0]["headings"] == list(HEADINGS)
    assert _emails(script) == ["early@shop.test", "ali@shop.test", "held@shop.test"]
    assert script.rows[1] == [
        "10.11.2026 11:30",
        "Ali Valiyev",
        "+998901112233",
        "ali@shop.test",
        "Biznes egasi",
    ]

    assert sweep_signup_sheet(db, now=NOW + timedelta(minutes=1)) == 0
    assert sweep_signup_sheet(db, now=NOW + timedelta(minutes=2)) == 1
    assert _emails(script)[-1] == "fresh@shop.test"


def test_paying_later_changes_nothing_in_the_sheet(
    db: Session, script: FakeScript
) -> None:
    plan = _plan(db)
    late = _user(db, "late@shop.test", NOW - timedelta(minutes=10))
    db.commit()
    assert sweep_signup_sheet(db, now=NOW) == 1

    _paid(db, late, plan)
    db.commit()
    assert sweep_signup_sheet(db, now=NOW + timedelta(minutes=1)) == 0

    assert _emails(script) == ["late@shop.test"]
    assert db.scalar(select(SignupSheetRow.owner_id)) == late.id


@pytest.mark.parametrize("failure", ["status", "denied"])
def test_a_refusal_writes_nothing_and_the_next_minute_does(
    db: Session,
    script: FakeScript,
    failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _user(db, "wait@shop.test", NOW - timedelta(minutes=10))
    db.commit()
    if failure == "status":
        script.status = 503
    else:
        script.answer = "denied"

    assert sweep_signup_sheet(db, now=NOW) == 0
    assert db.scalars(select(SignupSheetRow)).all() == []
    assert "token=" not in caplog.text

    script.status, script.answer = 200, "ok"
    assert sweep_signup_sheet(db, now=NOW + timedelta(minutes=1)) == 1
    assert _emails(script) == ["wait@shop.test"]


def test_off_without_a_url_and_while_another_run_holds_it(
    db: Session, script: FakeScript, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user(db, "x@shop.test", NOW - timedelta(minutes=10))
    db.commit()

    monkeypatch.setattr(settings, "signup_sheet_url", "")
    assert sweep_signup_sheet(db, now=NOW) == 0
    monkeypatch.setattr(settings, "signup_sheet_url", URL)

    cache.add(LOCK_KEY, "1", 60)
    assert sweep_signup_sheet(db, now=NOW) == 0
    cache.delete(LOCK_KEY)

    assert script.calls == 0
    assert sweep_signup_sheet(db, now=NOW) == 1


def test_a_written_account_can_still_be_deleted(
    db: Session, script: FakeScript
) -> None:
    from app.common.deletion import delete_rows

    gone = _user(db, "gone@shop.test", NOW - timedelta(minutes=10))
    db.commit()
    assert sweep_signup_sheet(db, now=NOW) == 1

    delete_rows(db, User.__table__, User.id == gone.id)
    db.commit()

    assert db.scalars(select(SignupSheetRow)).all() == []
