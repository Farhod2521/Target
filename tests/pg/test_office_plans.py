"""The office's plans: read by the admin roles, written by the superuser alone."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.billing.models import Plan, Subscription
from tests.pg.test_office_actions import _staff

URL = "/api/v1/office/plans"


def _new(**fields: object) -> dict[str, object]:
    return {
        "code": " Biznes ",
        "name": " Biznes ",
        "price": 790000,
        "period_days": 30,
        "included_pages": 5,
        "extra_page_price": 199000,
        "crm_seat_price": 40000,
    } | fields


def _plan(db: Session, code: str = "start", **fields: object) -> Plan:
    columns: dict[str, object] = {
        "name": code.title(),
        "price": 49000,
        "currency": "UZS",
        "period_days": 7,
        "max_adsets": 20,
        "llm_cost_limit_minor": 1000,
    }
    plan = Plan(code=code, **(columns | fields))
    db.add(plan)
    db.commit()
    return plan


def _subscribe(db: Session, plan: Plan, *, status: str = "active") -> Subscription:
    customer = User(
        email=f"{status}-{plan.code}@shop.test",
        full_name="Shop",
        password="!",
        date_joined=utcnow(),
    )
    db.add(customer)
    db.flush()
    now = utcnow()
    subscription = Subscription(
        owner_id=customer.id,
        plan_id=plan.id,
        status=status,
        started_at=now - timedelta(days=40),
        expires_at=now
        + (timedelta(days=5) if status != "expired" else -timedelta(days=10)),
    )
    db.add(subscription)
    db.commit()
    return subscription


def test_the_admin_roles_read_and_the_superuser_alone_writes(
    client: TestClient, db: Session
) -> None:
    plan = _plan(db)
    _, seller = _staff(db, Role.SALES, email="seller@office.test")
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, chief = _staff(db, email="chief@office.test", superuser=True)

    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=seller).status_code == 404
    read = client.get(URL, headers=support)
    assert read.status_code == 200, read.text
    assert read.json()["can_edit"] is False
    assert [row["code"] for row in read.json()["rows"]] == ["start"]
    assert client.get(f"{URL}/{plan.id}", headers=owner).status_code == 200

    for who in (support, owner):
        assert client.post(URL, headers=who, json=_new()).status_code == 404
        edit = client.put(f"{URL}/{plan.id}", headers=who, json=_new())
        assert edit.status_code == 404
        assert client.delete(f"{URL}/{plan.id}", headers=who).status_code == 404
    db.refresh(plan)
    assert plan.price == 49000

    assert client.get(URL, headers=chief).json()["can_edit"] is True
    made = client.post(URL, headers=chief, json=_new())
    assert made.status_code == 200, made.text
    row = db.scalar(select(Plan).where(Plan.code == "biznes"))
    assert row is not None
    assert (row.name, row.currency, row.included_pages) == ("Biznes", "UZS", 5)
    assert (row.crm_seat_price, row.is_active) == (40000, True)


def test_a_plan_is_checked_before_it_is_written(
    client: TestClient, db: Session
) -> None:
    plan = _plan(db)
    _, chief = _staff(db, email="chief@office.test", superuser=True)

    for code in ("", "biz nes", "бизнес", "a" * 33, " START "):
        refused = client.post(URL, headers=chief, json=_new(code=code))
        assert refused.status_code == 422, code
    taken = client.post(URL, headers=chief, json=_new(code="start"))
    assert taken.json()["problems"] == {"code": "Bu kod allaqachon bor."}
    blank = client.post(URL, headers=chief, json=_new(name="  "))
    assert blank.json()["problems"] == {"name": "Nomini yozing."}
    for wrong in (
        {"price": -1},
        {"period_days": 0},
        {"included_pages": 0},
        {"daily_chat_requests": -5},
        {"extra_page_price": -1},
        {"llm_cost_limit_minor": -1},
    ):
        assert client.post(URL, headers=chief, json=_new(**wrong)).status_code == 422

    edited = client.put(
        f"{URL}/{plan.id}",
        headers=chief,
        json=_new(code="renamed", name="Start", price=59000, features=" a  \n\n*b \n"),
    )
    assert edited.status_code == 200, edited.text
    db.refresh(plan)
    assert (plan.code, plan.price, plan.features) == ("start", 59000, "a\n\n*b")
    assert (
        client.put(f"{URL}/{plan.id}x", headers=chief, json=_new()).status_code == 422
    )
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.put(f"{URL}/{missing}", headers=chief, json=_new()).status_code == 404


def test_the_list_counts_live_subscriptions_and_marks_the_trial(
    client: TestClient, db: Session
) -> None:
    start = _plan(db)
    pro = _plan(db, "pro", sort_order=2, price=1990000)
    _plan(db, "old", is_active=False, sort_order=-5)
    _subscribe(db, start, status="trial")
    _subscribe(db, start)
    _subscribe(db, pro, status="expired")
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")

    body = client.get(URL, headers=finance).json()
    rows = {row["code"]: row for row in body["rows"]}
    assert [row["code"] for row in body["rows"]] == ["start", "pro", "old"]
    assert (rows["start"]["live"], rows["pro"]["live"], rows["old"]["live"]) == (
        2,
        0,
        0,
    )
    assert rows["start"]["is_trial"] and not rows["pro"]["is_trial"]
    assert [rows[code]["deletable"] for code in ("start", "pro", "old")] == [
        False,
        False,
        True,
    ]
    assert body["llm_currency"]
    one = client.get(f"{URL}/{start.id}", headers=finance).json()
    assert one["live"] == 2 and one["price"] == 49000


def test_a_used_plan_is_taken_off_sale_not_deleted(
    client: TestClient, db: Session
) -> None:
    used = _plan(db)
    _subscribe(db, used, status="expired")
    spare_id = _plan(db, "spare").id
    chief_user, chief = _staff(db, email="chief@office.test", superuser=True)

    refused = client.delete(f"{URL}/{used.id}", headers=chief)
    assert refused.status_code == 400
    assert refused.json()["code"] == "plan_in_use"
    assert db.get(Plan, used.id) is not None

    off = client.put(
        f"{URL}/{used.id}",
        headers=chief,
        json=_new(name="Start", price=49000, period_days=7, is_active=False),
    )
    assert off.status_code == 200, off.text
    gone = client.delete(f"{URL}/{spare_id}", headers=chief)
    assert gone.status_code == 200, gone.text
    db.expire_all()
    assert db.get(Plan, spare_id) is None

    traces = db.scalars(
        select(StaffAction)
        .where(StaffAction.owner_id == chief_user.id)
        .order_by(StaffAction.created_at)
    ).all()
    assert [trace.kind for trace in traces] == [
        ActionKind.PLAN_UPDATED,
        ActionKind.PLAN_DELETED,
    ]
    changed = traces[0].detail["changed"]
    assert changed["Sotuvda"] == ["True", "False"]
    assert changed["Sahifalar"] == ["1", "5"]
    assert "Kod" not in changed
    assert traces[1].detail["code"] == "spare"
