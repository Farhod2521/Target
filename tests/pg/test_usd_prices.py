"""Dollar prices: the plans' USD fields, the account's country and who sets it."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.money import to_minor
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.billing.models import Invoice, Plan
from app.modules.billing.selectors.pages import page_price_minor
from app.modules.billing.selectors.prices import price_book
from app.modules.billing.selectors.seats import seat_price_minor
from tests.pg.conftest import sign_up
from tests.pg.test_office_actions import _staff
from tests.pg.test_office_plans import _plan


def test_the_superuser_sets_a_plan_s_dollar_prices(
    client: TestClient, db: Session
) -> None:
    plan = _plan(db, "standard", price=590000)
    _, chief = _staff(db, email="chief@office.test", superuser=True)
    shown = client.get(f"/api/v1/office/plans/{plan.id}", headers=chief).json()

    saved = client.put(
        f"/api/v1/office/plans/{plan.id}",
        json={
            k: v
            for k, v in shown.items()
            if k
            in {
                "name",
                "tagline",
                "features",
                "price",
                "period_days",
                "max_adsets",
                "daily_chat_requests",
                "llm_cost_limit_minor",
                "included_pages",
                "included_google_accounts",
                "extra_page_price",
                "crm_seat_price",
                "is_one_time",
                "is_active",
                "sort_order",
            }
        }
        | {
            "price_usd_cents": 4900,
            "extra_page_price_usd_cents": 1500,
            "crm_seat_price_usd_cents": 400,
        },
        headers=chief,
    )

    assert saved.status_code == 200, saved.text
    db.expire_all()
    assert (
        plan.price_usd_cents,
        plan.extra_page_price_usd_cents,
        plan.crm_seat_price_usd_cents,
    ) == (4900, 1500, 400)
    again = client.get(f"/api/v1/office/plans/{plan.id}", headers=chief).json()
    assert again["price_usd_cents"] == 4900


def test_the_account_country_is_set_once_from_its_first_address(
    client: TestClient, db: Session
) -> None:
    auth = sign_up(client)

    client.get("/api/v1/billing/status", headers=auth | {"CF-IPCountry": "JP"})
    client.get("/api/v1/billing/status", headers=auth | {"CF-IPCountry": "UZ"})

    user = db.scalar(select(User))
    assert user is not None
    db.refresh(user)
    assert user.country == "JP"


def test_the_owner_changes_a_customer_s_country_with_a_reason(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    customer = db.scalar(select(User))
    assert customer is not None
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    url = f"/api/v1/office/customers/{customer.id}/country"

    refused = client.post(url, json={"country": "US", "reason": "x"}, headers=support)
    wrong = client.post(url, json={"country": "1A", "reason": "x"}, headers=owner)
    done = client.post(
        url, json={"country": "us", "reason": "Yaponiyada yashaydi"}, headers=owner
    )

    assert refused.status_code == 404
    assert wrong.status_code == 422
    assert done.status_code == 200, done.text
    db.refresh(customer)
    assert customer.country == "US"
    row = db.scalar(
        select(StaffAction).where(StaffAction.kind == str(ActionKind.COUNTRY_SET))
    )
    assert row is not None and row.detail == {"from": "", "to": "US"}
    card = client.get(f"/api/v1/office/customers/{customer.id}", headers=owner).json()
    assert card["profile"]["country"] == "US"


# --- Stage 2: what an account abroad is billed ------------------------------

RATE = (Decimal("12650.37"), "25.11.2026")


def _sold_plan(db: Session, **fields: object) -> Plan:
    plan = Plan(
        **(
            {
                "code": "pro",
                "name": "Pro",
                "tagline": "",
                "features": "",
                "price": 590000,
                "currency": "UZS",
                "period_days": 30,
                "max_adsets": 10,
                "daily_chat_requests": 20,
                "llm_cost_limit_minor": 1000,
                "included_pages": 1,
                "included_google_accounts": 0,
                "extra_page_price": 150000,
                "crm_seat_price": 40000,
                "price_usd_cents": 4900,
                "extra_page_price_usd_cents": 1500,
                "crm_seat_price_usd_cents": 400,
                "is_one_time": False,
                "is_active": True,
                "sort_order": 1,
            }
            | fields
        )
    )
    db.add(plan)
    db.commit()
    return plan


def _som_minor(som: int) -> int:
    return int(to_minor(amount=str(som), currency="UZS"))


@pytest.fixture
def rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.modules.billing.selectors.prices.usd_rate", lambda: RATE)


def _account(db: Session, client: TestClient, country: str) -> dict[str, str]:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    user.country = country
    db.commit()
    return auth


def test_abroad_the_plan_is_billed_its_dollars_at_the_day_s_rate(
    client: TestClient, db: Session, rate: None
) -> None:
    _sold_plan(db)
    auth = _account(db, client, "JP")
    # $49 at 12 650,37 so'm is 619 868,13: rounded up to the whole so'm.
    due = _som_minor(619869)

    shown = client.get("/api/v1/billing?plan=pro", headers=auth)
    client.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=auth)

    assert shown.status_code == 200, shown.text
    assert shown.json()["chosen"]["due_minor"] == due
    invoice = db.scalar(select(Invoice))
    assert invoice is not None
    assert invoice.amount_minor == due
    assert invoice.currency == "UZS"
    assert invoice.usd_rate == "12650.37"


def test_at_home_the_so_m_price_stands(
    client: TestClient, db: Session, rate: None
) -> None:
    _sold_plan(db)
    auth = _account(db, client, "UZ")

    client.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=auth)

    invoice = db.scalar(select(Invoice))
    assert invoice is not None
    assert invoice.amount_minor == _som_minor(590000)
    assert invoice.usd_rate == ""


def test_abroad_a_plan_with_no_dollar_price_keeps_its_so_m_price(
    client: TestClient, db: Session, rate: None
) -> None:
    _sold_plan(db, price_usd_cents=0)
    auth = _account(db, client, "JP")

    client.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=auth)

    invoice = db.scalar(select(Invoice))
    assert invoice is not None
    assert invoice.amount_minor == _som_minor(590000)


def test_the_price_book_rounds_up_and_keeps_a_bill_s_rate() -> None:
    plan = Plan(
        price=590000,
        extra_page_price=150000,
        crm_seat_price=40000,
        price_usd_cents=4900,
        extra_page_price_usd_cents=1500,
        crm_seat_price_usd_cents=0,
        currency="UZS",
    )
    abroad = User(country="KZ")

    kept = price_book(abroad, kept_rate="12000")
    home = price_book(User(country="UZ"))
    unknown = price_book(User(country=""))

    assert (kept.plan_som(plan), kept.page_som(plan), kept.seat_som(plan)) == (
        588000,
        180000,
        40000,
    )
    assert home.plan_som(plan) == unknown.plan_som(plan) == 590000
    assert kept.kept_rate == "12000" and home.kept_rate == ""


# --- Stage 3: what an account abroad is shown -------------------------------


def test_abroad_an_account_is_shown_its_dollars_wherever_it_reads_from(
    client: TestClient, db: Session, rate: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.modules.billing.selectors.display.usd_rate", lambda: RATE)
    _sold_plan(db, price_usd_cents=4900, extra_page_price_usd_cents=0)
    auth = _account(db, client, "JP")

    # Reading from Uzbekistan changes nothing: the account's country decides.
    page = client.get(
        "/api/v1/billing?plan=pro", headers=auth | {"CF-IPCountry": "UZ"}
    ).json()

    assert page["display"]["currency"] == "USD"
    card = next(p for p in page["plans"] if p["code"] == "pro")
    assert card["shown"]["price"] == 49.0
    assert card["shown"]["approximate"] is False
    assert card["price"] == 619869
    # No dollar price for a page: the so'm one over the rate, marked approximate.
    assert card["shown"]["extra_page_price"] == round(150000 / 12650.37, 2)


def test_at_home_an_account_is_shown_so_m_even_from_abroad(
    client: TestClient, db: Session, rate: None
) -> None:
    _sold_plan(db)
    auth = _account(db, client, "UZ")

    page = client.get(
        "/api/v1/billing?plan=pro", headers=auth | {"CF-IPCountry": "JP"}
    ).json()

    assert page["display"]["currency"] == "UZS"
    card = next(p for p in page["plans"] if p["code"] == "pro")
    assert card["price"] == 590000


def test_a_bill_abroad_carries_its_rate_to_the_history(
    client: TestClient, db: Session, rate: None
) -> None:
    _sold_plan(db)
    auth = _account(db, client, "JP")
    client.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=auth)
    invoice = db.scalar(select(Invoice))
    assert invoice is not None

    shown = client.get(f"/api/v1/billing/invoice/{invoice.number}", headers=auth)

    assert shown.json()["invoice"]["usd_rate"] == "12650.37"


def test_the_office_reads_the_rate_and_a_bill_s_own(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.modules.billing.selectors.display.usd_rate", lambda: RATE)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    shown = client.get("/api/v1/office/rate", headers=support)

    assert shown.status_code == 200, shown.text
    assert shown.json() == {"uzs_per_usd": "12650.37", "rate_date": "25.11.2026"}
    assert client.get("/api/v1/office/rate").status_code == 401


# --- Review fixes: a bill keeps its own basis --------------------------------


def test_an_unpaid_so_m_bill_is_not_offered_to_an_account_now_abroad(
    client: TestClient, db: Session, rate: None
) -> None:
    _sold_plan(db)
    auth = _account(db, client, "UZ")
    client.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=auth)
    user = db.scalar(select(User))
    assert user is not None
    user.country = "JP"
    db.commit()

    client.post("/api/v1/billing/checkout", json={"plan": "pro"}, headers=auth)

    bills = db.scalars(select(Invoice).order_by(Invoice.created_at)).all()
    assert [(b.usd_rate, b.amount_minor) for b in bills] == [
        ("", _som_minor(590000)),
        ("12650.37", _som_minor(619869)),
    ]


def test_what_is_added_to_a_bill_is_priced_on_the_bill_s_basis(rate: None) -> None:
    plan = Plan(
        price=590000,
        extra_page_price=150000,
        crm_seat_price=40000,
        price_usd_cents=4900,
        extra_page_price_usd_cents=1500,
        crm_seat_price_usd_cents=400,
        currency="UZS",
        period_days=30,
    )
    abroad = User(country="JP")

    on_som_bill = page_price_minor(plan=plan, owner=abroad, bill_rate="")
    on_dollar_bill = seat_price_minor(plan=plan, owner=None, bill_rate="12000")

    assert on_som_bill == _som_minor(150000)
    assert on_dollar_bill == _som_minor(48000)
