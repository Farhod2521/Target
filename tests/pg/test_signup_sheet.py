"""Sign-ups who did not pay in five minutes, written to the sales team's sheet.

Google is an httpx.MockTransport: the token endpoint, the sheet's tabs, and
appendCells. The key is a real RSA key, so the signed request is real.
"""

import json
from datetime import datetime, timedelta
from typing import Any

import googlekit.sheets
import googlekit.transport
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.sales.models import SignupSheetRow
from app.modules.sales.services.signup_sheet import (
    HEADINGS,
    LOCK_KEY,
    STARTS_AT,
    ZONE,
    sweep_signup_sheet,
)

SHEET = "sheet-1"
TOKEN = "https://oauth2.googleapis.com/token"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=ZONE)

_PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode()
)


class FakeGoogle:
    def __init__(self) -> None:
        self.rows: list[list[Any]] = []
        self.down = False
        self.tokens = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url == TOKEN:
            self.tokens += 1
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3599})
        assert request.headers["Authorization"] == "Bearer at"
        if self.down:
            return httpx.Response(503, json={"error": {"message": "later"}})
        if url == f"{SHEETS}/{SHEET}":
            tabs = [{"properties": {"sheetId": 777, "title": "Varaq1"}}]
            return httpx.Response(200, json={"spreadsheetId": SHEET, "sheets": tabs})
        assert url == f"{SHEETS}/{SHEET}:batchUpdate"
        (only,) = json.loads(request.content)["requests"]
        assert only["appendCells"]["sheetId"] == 777
        for row in only["appendCells"]["rows"]:
            self.rows.append(
                [
                    next(iter(value.get("userEnteredValue", {"": ""}).values()))
                    for value in row["values"]
                ]
            )
        return httpx.Response(200, json={"spreadsheetId": SHEET})


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    fake = FakeGoogle()

    def client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(fake.handle))

    monkeypatch.setattr(googlekit.transport, "new_client", client)
    monkeypatch.setattr(googlekit.sheets, "new_client", client)
    key = {"client_email": "sa@p.iam.gserviceaccount.com", "private_key": _PEM}
    monkeypatch.setattr(settings, "google_service_account", json.dumps(key))
    monkeypatch.setattr(settings, "signup_sheet_id", SHEET)
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


def _emails(google: FakeGoogle) -> list[str]:
    return [row[3] for row in google.rows if row[3] != "Email"]


def test_unpaid_owners_from_the_start_date_are_written_once_with_a_heading(
    db: Session, google: FakeGoogle
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

    assert google.rows[0] == list(HEADINGS)
    assert _emails(google) == ["early@shop.test", "ali@shop.test", "held@shop.test"]
    ali = google.rows[2]
    assert ali[1:] == ["Ali Valiyev", "+998901112233", "ali@shop.test", "Biznes egasi"]
    # 11:30 in Tashkent, as Sheets counts days: the zone is the office's.
    assert ali[0] == pytest.approx(46_336 + 11.5 / 24)

    assert sweep_signup_sheet(db, now=NOW + timedelta(minutes=1)) == 0
    assert sweep_signup_sheet(db, now=NOW + timedelta(minutes=2)) == 1
    assert _emails(google)[-1] == "fresh@shop.test"
    assert google.rows.count(list(HEADINGS)) == 1


def test_paying_later_changes_nothing_in_the_sheet(
    db: Session, google: FakeGoogle
) -> None:
    plan = _plan(db)
    late = _user(db, "late@shop.test", NOW - timedelta(minutes=10))
    db.commit()
    assert sweep_signup_sheet(db, now=NOW) == 1

    _paid(db, late, plan)
    db.commit()
    assert sweep_signup_sheet(db, now=NOW + timedelta(minutes=1)) == 0

    assert _emails(google) == ["late@shop.test"]
    assert db.scalar(select(SignupSheetRow.owner_id)) == late.id


def test_google_down_writes_nothing_and_the_next_minute_does(
    db: Session, google: FakeGoogle
) -> None:
    _user(db, "wait@shop.test", NOW - timedelta(minutes=10))
    db.commit()
    google.down = True

    assert sweep_signup_sheet(db, now=NOW) == 0
    assert db.scalars(select(SignupSheetRow)).all() == []

    google.down = False
    assert sweep_signup_sheet(db, now=NOW + timedelta(minutes=1)) == 1
    assert _emails(google) == ["wait@shop.test"]


def test_off_without_a_key_or_a_sheet_and_while_another_run_holds_it(
    db: Session, google: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user(db, "x@shop.test", NOW - timedelta(minutes=10))
    db.commit()

    monkeypatch.setattr(settings, "signup_sheet_id", "")
    assert sweep_signup_sheet(db, now=NOW) == 0
    monkeypatch.setattr(settings, "signup_sheet_id", SHEET)

    cache.add(LOCK_KEY, "1", 60)
    assert sweep_signup_sheet(db, now=NOW) == 0
    cache.delete(LOCK_KEY)

    assert google.tokens == 0
    assert sweep_signup_sheet(db, now=NOW) == 1


def test_a_written_account_can_still_be_deleted(
    db: Session, google: FakeGoogle
) -> None:
    from app.common.deletion import delete_rows

    gone = _user(db, "gone@shop.test", NOW - timedelta(minutes=10))
    db.commit()
    assert sweep_signup_sheet(db, now=NOW) == 1

    delete_rows(db, User.__table__, User.id == gone.id)
    db.commit()

    assert db.scalars(select(SignupSheetRow)).all() == []
