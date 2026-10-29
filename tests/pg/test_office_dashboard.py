"""The office's first screen: the window, the money and who may see it,
the customer figures, the queues and the sales."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.billing.constants import InvoiceKind, InvoiceStatus
from app.modules.billing.models import Invoice, Plan
from app.modules.sales.constants import Outcome
from app.modules.sales.models import SalesClaim
from tests.pg.test_office_actions import _shop, _staff
from tests.pg.test_supportchat import _send, _user

URL = "/api/v1/office/dashboard"


def _bill(db: Session, plan: Plan, owner_id: object, **fields: object) -> None:
    number = f"TA-{db.scalar(select(func.count(Invoice.id))) + 1:04d}"
    db.add(
        Invoice(
            owner_id=owner_id,
            number=number,
            plan_id=plan.id,
            currency="UZS",
            period_days=30,
            expires_at=utcnow() + timedelta(days=30),
            **fields,
        )
    )
    db.flush()


def test_money_figures_and_who_sees_them(client: TestClient, db: Session) -> None:
    shop, plan = _shop(db)
    now = utcnow()
    _bill(db, plan, shop.id, amount_minor=49000000, status=InvoiceStatus.PAID,
          paid_at=now, manual_method="cash")  # fmt: skip
    _bill(db, plan, shop.id, amount_minor=6000000, status=InvoiceStatus.PAID,
          paid_at=now, kind=InvoiceKind.SEATS)  # fmt: skip
    _bill(db, plan, shop.id, amount_minor=10000000, status=InvoiceStatus.PAID,
          paid_at=now - timedelta(days=9))  # fmt: skip
    _bill(db, plan, shop.id, amount_minor=1, status=InvoiceStatus.PENDING)
    member, _ = _staff(db, Role.SUPPORT, email="support@office.test")
    db.add(StaffAction(owner_id=shop.id, actor_id=member.id,
                       kind=ActionKind.DAYS_GRANTED, detail={"days": 3}))  # fmt: skip
    db.commit()
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    _, support = _staff(db, Role.SUPPORT, email="s2@office.test")

    seen = client.get(URL, headers=finance, params={"period": "7"})
    assert seen.status_code == 200, seen.text
    body = seen.json()
    money = body["takings"]
    assert len(money["bars"]) == 7 and money["bars"][-1]["is_current"]
    assert money["shown"]["amount_minor"] == 55000000
    assert money["shown"]["manual_minor"] == 49000000
    assert [(p["name"], p["share_pct"]) for p in money["shown"]["plans"]] == [
        ("Pro", 89),
        ("CRM menejeri", 11),
    ], "a seats bill sold seats, not its plan"
    assert money["before_minor"] == 10000000 and money["change_pct"] == 450
    assert (money["unpaid"], money["given_free"]) == (1, 1)
    assert [row["amount_minor"] for row in body["payments"]][:2] == [49000000, 6000000]

    today = localtime(utcnow()).date().isoformat()
    picked = client.get(
        f"{URL}/takings", headers=finance, params={"period": "7", "bar": today}
    )
    assert picked.json()["picked"] == today

    hidden = client.get(URL, headers=support).json()
    assert hidden["sees_money"] is False
    assert hidden["takings"] is None and hidden["payments"] is None
    assert hidden["activity"]["ai_cost"] is None
    assert client.get(f"{URL}/takings", headers=support).status_code == 404

    refused = client.get(
        URL, headers=finance, params={"period": "range", "since": today}
    )
    assert refused.json()["window"]["refused"] == "Ikkala sanani ham tanlang."


def test_customers_queues_and_sales(client: TestClient, db: Session) -> None:
    shop, _ = _shop(db)
    fresh = _user(db, "yangi@example.com")
    seller, _ = _staff(db, Role.SALES, email="seller@office.test")
    db.add_all(
        [
            SalesClaim(owner_id=shop.id, manager_id=seller.id, outcome=Outcome.SOLD,
                       claimed_at=utcnow(), expires_at=utcnow(), closed_at=utcnow()),
            SalesClaim(owner_id=fresh.id, manager_id=seller.id, claimed_at=utcnow(),
                       expires_at=utcnow() + timedelta(days=1)),
        ]
    )  # fmt: skip
    db.commit()
    _send(client, fresh, body="Salom")
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    body = client.get(URL, headers=support, params={"period": "30"}).json()
    people = body["customers"]
    assert people["total"] == 2, "staff are not customers"
    assert people["joined"] == 2 and people["paying"] == 1
    assert people["meta_missing"] == 1
    assert body["waiting"]["support"] == 1
    assert body["waiting"]["support_oldest"] is not None
    assert body["sales"] == [
        {
            "manager": {"id": str(seller.id), "name": "seller@office.test",
                        "email": "seller@office.test"},
            "sold": 1,
            "open": 1,
        }
    ]  # fmt: skip
    assert body["problems"]["rows"] == [] or body["problems"]["rows"][0]["label"]
