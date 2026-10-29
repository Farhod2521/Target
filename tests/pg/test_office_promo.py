"""The office's promo screen: the request queue and the catalogue's writes."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.billing.constants import RedemptionStatus, SubscriptionStatus
from app.modules.billing.models import PromoCode, PromoRedemption, Subscription
from app.modules.billing.services import redeem_promo
from tests.pg.test_office_actions import _shop, _staff

URL = "/api/v1/office/promo"


def _days_code(**figures: object) -> dict[str, object]:
    return {
        "kind": "plan",
        "code": " bahor7 ",
        "grant_days": 7,
        "expires_at": (utcnow() + timedelta(days=30)).isoformat(),
        "max_uses": 10,
        "needs_approval": True,
    } | figures


def test_the_catalogue_is_written_by_finance_and_journalled(
    client: TestClient, db: Session
) -> None:
    finance, money = _staff(db, Role.FINANCE, email="finance@office.test")
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    assert (
        client.post(f"{URL}/codes", headers=support, json=_days_code()).status_code
        == 404
    )
    unbounded = client.post(
        f"{URL}/codes",
        headers=money,
        json=_days_code(expires_at=None, max_uses=0, grant_days=0),
    )
    assert unbounded.status_code == 422
    assert set(unbounded.json()["problems"]) == {"expires_at", "max_uses", "grant_days"}

    made = client.post(
        f"{URL}/codes", headers=money, json=_days_code(discount_value=50)
    )
    assert made.status_code == 200, made.text
    code = db.get(PromoCode, made.json()["id"])
    assert code is not None and code.code == "BAHOR7"
    assert code.discount_value == 0, "another kind's figures never land"
    clash = client.post(f"{URL}/codes", headers=money, json=_days_code())
    assert clash.json()["problems"] == {"code": "Bu kod allaqachon bor."}

    discount = client.post(
        f"{URL}/codes",
        headers=money,
        json={
            "kind": "discount",
            "code": "MINUS",
            "discount_kind": "amount",
            "discount_value": 50000,
            "min_amount": 100000,
        },
    )
    assert discount.status_code == 200, discount.text
    stored = db.get(PromoCode, discount.json()["id"])
    assert stored is not None
    assert (stored.discount_value, stored.min_amount_minor) == (5000000, 10000000)
    percent = client.post(
        f"{URL}/codes",
        headers=money,
        json={
            "kind": "discount",
            "code": "ALL",
            "discount_kind": "percent",
            "discount_value": 100,
        },
    )
    assert percent.json()["problems"] == {
        "discount_value": "Foiz 1 dan 99 gacha bo'lishi kerak."
    }

    edited = client.put(
        f"{URL}/codes/{code.id}",
        headers=money,
        json=_days_code(kind="slots", grant_days=14, grant_pages=3),
    )
    assert edited.status_code == 200, edited.text
    db.expire_all()
    assert (code.kind, code.grant_days, code.grant_pages) == ("plan", 14, 0)

    listed = client.get(URL, headers=support).json()
    rows = {row["code"]: row for row in listed["current"]}
    assert rows["MINUS"]["discount_value"] == 50000
    assert rows["MINUS"]["min_amount"] == 100000
    assert rows["BAHOR7"]["status"] == "live"

    assert client.delete(f"{URL}/codes/{stored.id}", headers=money).status_code == 200
    changes = list(
        db.scalars(
            select(StaffAction)
            .where(StaffAction.owner_id == finance.id)
            .order_by(StaffAction.created_at)
        )
    )
    assert [row.kind for row in changes] == [
        ActionKind.PROMO_CODE_CREATED,
        ActionKind.PROMO_CODE_CREATED,
        ActionKind.PROMO_CODE_UPDATED,
        ActionKind.PROMO_CODE_DELETED,
    ]
    assert changes[2].detail["changed"] == {"Beriladigan kun": ["7", "14"]}


def test_a_request_is_answered_once_and_a_used_code_is_kept(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    other = _shop_two(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, money = _staff(db, Role.FINANCE, email="finance@office.test")
    made = client.post(f"{URL}/codes", headers=money, json=_days_code())
    code_id = made.json()["id"]
    redeem_promo(db, user=customer, code="BAHOR7", now=utcnow())
    redeem_promo(db, user=other, code="bahor7", now=utcnow())
    db.commit()

    queue = client.get(URL, headers=support, params={"q": "shop@"}).json()
    assert queue["total"] == 1
    first = queue["requests"][0]
    assert first["offers"]["days"] == 7 and first["refused_before"] == 0
    assert queue["current"][0]["used"] == 2

    before = db.scalar(select(Subscription).where(Subscription.owner_id == customer.id))
    assert before is not None
    until = before.expires_at
    approved = client.post(f"{URL}/requests/{first['id']}/approve", headers=support)
    assert approved.status_code == 200, approved.text
    again = client.post(f"{URL}/requests/{first['id']}/approve", headers=support)
    assert again.status_code == 400
    db.expire_all()
    assert before.expires_at == until + timedelta(days=7)

    second = client.get(URL, headers=support).json()["requests"][0]
    refused = client.post(
        f"{URL}/requests/{second['id']}/refuse",
        headers=support,
        json={"reason": "Shartga mos emas"},
    )
    assert refused.status_code == 200, refused.text
    answered = client.get(URL, headers=support, params={"tab": "answered"}).json()
    assert [row["status"] for row in answered["requests"]] == [
        RedemptionStatus.REJECTED,
        RedemptionStatus.APPROVED,
    ]
    assert answered["requests"][0]["decision_note"] == "Shartga mos emas"
    assert answered["requests"][0]["decided_by"]["email"] == "support@office.test"

    kept = client.delete(f"{URL}/codes/{code_id}", headers=money)
    assert kept.status_code == 400
    assert db.scalar(select(PromoRedemption.id).limit(1)) is not None
    assert [
        kind
        for kind in db.scalars(
            select(StaffAction.kind)
            .where(StaffAction.kind.in_(["promo_approved", "promo_rejected"]))
            .order_by(StaffAction.created_at)
        )
    ] == [ActionKind.PROMO_APPROVED, ActionKind.PROMO_REJECTED]


def _shop_two(db: Session) -> User:
    """A second subscribed customer, on the first one's plan."""
    owner = User(
        email="cafe@client.test", full_name="Cafe", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.flush()
    now = utcnow()
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=db.scalar(select(Subscription.plan_id).limit(1)),
            status=SubscriptionStatus.ACTIVE,
            started_at=now,
            expires_at=now + timedelta(days=5),
        )
    )
    db.commit()
    return owner
