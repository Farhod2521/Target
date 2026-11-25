"""Dollar prices: the plans' USD fields, the account's country and who sets it."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
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
