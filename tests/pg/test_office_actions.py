"""The writes on a customer's card, against PostgreSQL with Django's foreign keys."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import utcnow
from app.common.passwords import check_password
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.integrations.models import PageAccount, ProviderConnection
from app.modules.referrals.models import ReferralAccess, ReferralBinding

URL = "/api/v1/office/customers"


def _staff(
    db: Session, *roles: Role, email: str, superuser: bool = False
) -> tuple[User, dict[str, str]]:
    member = User(
        email=email,
        full_name=email,
        password="!",
        is_staff=True,
        is_superuser=superuser,
        date_joined=utcnow(),
    )
    db.add(member)
    db.flush()
    for role in roles:
        group = db.scalar(select(Group).where(Group.name == str(role)))
        if group is None:
            group = Group(name=str(role))
            db.add(group)
            db.flush()
        db.add(UserGroup(user_id=member.id, group_id=group.id))
    db.commit()
    return member, _bearer(member)


def _bearer(user: User) -> dict[str, str]:
    token = tokens.issue(subject=str(user.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def _shop(db: Session, *, subscribed: bool = True) -> tuple[User, Plan]:
    plan = db.scalar(select(Plan).where(Plan.code == "pro"))
    if plan is None:
        plan = Plan(
            code="pro",
            name="Pro",
            price=490000,
            currency="UZS",
            period_days=30,
            max_adsets=10,
            llm_cost_limit_minor=1000,
        )
        db.add(plan)
    customer = User(
        email="shop@client.test",
        full_name="Shop",
        password="!",
        date_joined=utcnow() - timedelta(days=3),
    )
    db.add(customer)
    db.flush()
    if subscribed:
        now = utcnow()
        db.add(
            Subscription(
                owner_id=customer.id,
                plan_id=plan.id,
                status=SubscriptionStatus.ACTIVE,
                started_at=now - timedelta(days=10),
                expires_at=now + timedelta(days=20),
            )
        )
    db.commit()
    return customer, plan


def _kinds(db: Session, customer: User) -> list[str]:
    return list(
        db.scalars(
            select(StaffAction.kind)
            .where(StaffAction.owner_id == customer.id)
            .order_by(StaffAction.created_at)
        )
    )


def test_plan_days_slots_payment_and_referral(client: TestClient, db: Session) -> None:
    customer, _ = _shop(db, subscribed=False)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    base = f"{URL}/{customer.id}"

    given = client.post(
        f"{base}/plan", headers=support, json={"plan": "pro", "reason": "Sinov"}
    )
    assert given.status_code == 200, given.text
    assert given.json() == {"message": "Tarif berildi."}

    unpaid = client.post(
        f"{base}/days",
        headers=support,
        json={"days": 5, "reason": "Pul keldi", "paid": True},
    )
    assert unpaid.status_code == 422
    assert set(unpaid.json()["problems"]) == {"amount", "method"}

    paid = client.post(
        f"{base}/days",
        headers=support,
        json={
            "days": 5,
            "reason": "Naqd to'ladi",
            "paid": True,
            "amount": "100000",
            "method": "cash",
        },
    )
    assert paid.status_code == 200, paid.text
    bill = db.scalar(select(Invoice).where(Invoice.owner_id == customer.id))
    assert bill is not None and bill.status == InvoiceStatus.PAID
    assert bill.amount_minor == 10000000 and bill.manual_method == "cash"

    assert (
        client.post(
            f"{base}/slots",
            headers=support,
            json={"pages": 2, "reason": "Sovg'a"},
        ).status_code
        == 200
    )
    refused = client.post(
        f"{base}/slots",
        headers=support,
        json={"pages": 1, "reason": "Xato", "take": True, "paid": True},
    )
    assert refused.status_code == 422
    assert (
        client.post(
            f"{base}/slots",
            headers=support,
            json={"pages": 1, "reason": "Xato", "take": True},
        ).status_code
        == 200
    )
    db.expire_all()
    subscription = db.scalar(
        select(Subscription).where(Subscription.owner_id == customer.id)
    )
    assert subscription is not None and subscription.extra_pages == 1

    recorded = client.post(
        f"{base}/payment",
        headers=support,
        json={"amount": "50000", "method": "transfer", "reason": "O'tkazma"},
    )
    assert recorded.status_code == 200, recorded.text

    closed = client.post(
        f"{base}/referral", headers=support, json={"mode": "closed", "reason": "Spam"}
    )
    assert closed.status_code == 200, closed.text
    access = db.scalar(
        select(ReferralAccess).where(ReferralAccess.owner_id == customer.id)
    )
    assert access is not None and access.mode == "closed"

    assert _kinds(db, customer) == [
        ActionKind.PLAN_GIVEN,
        ActionKind.DAYS_GRANTED,
        ActionKind.PAGES_GRANTED,
        ActionKind.PAGES_REVOKED,
        ActionKind.PAYMENT_RECORDED,
        ActionKind.REFERRAL_CHANGED,
    ]


def test_a_refusal_is_a_domain_error_and_roles_are_kept(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db, subscribed=False)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, seller = _staff(db, Role.SALES, email="seller@office.test")
    base = f"{URL}/{customer.id}"

    nothing = client.post(
        f"{base}/days", headers=support, json={"days": 5, "reason": "x"}
    )
    assert nothing.status_code == 400
    assert (
        client.post(
            f"{base}/days", headers=seller, json={"days": 5, "reason": "x"}
        ).status_code
        == 404
    )
    payout = {"amount": "10", "currency": "UZS", "method": "cash", "reason": "x"}
    assert (
        client.post(f"{base}/payout", headers=support, json=payout).status_code == 404
    )
    assert (
        client.post(
            f"{base}/delete", headers=support, json={"email": customer.email}
        ).status_code
        == 404
    )
    assert _kinds(db, customer) == []


def test_moving_a_page_hands_its_slot_over(client: TestClient, db: Session) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    link = ProviderConnection(
        owner_id=customer.id, provider="meta", token_encrypted=b"x", status="active"
    )
    db.add(link)
    db.flush()
    paid_for = PageAccount(
        owner_id=customer.id,
        provider="meta",
        external_id="p1",
        connection_id=link.id,
        name="Wrong page",
        token_encrypted=b"x",
        is_active=True,
        is_current=True,
    )
    wanted = PageAccount(
        owner_id=customer.id,
        provider="meta",
        external_id="p2",
        connection_id=link.id,
        name="Right page",
        token_encrypted=b"x",
    )
    db.add_all([paid_for, wanted])
    db.commit()

    moved = client.post(
        f"{URL}/{customer.id}/pages/{paid_for.id}/move",
        headers=support,
        json={"target": str(wanted.id), "reason": "Noto'g'ri sahifa to'langan"},
    )
    assert moved.status_code == 200, moved.text
    db.expire_all()
    assert db.get(PageAccount, paid_for.id).is_active is False  # type: ignore[union-attr]
    assert db.get(PageAccount, wanted.id).is_active is True  # type: ignore[union-attr]
    assert _kinds(db, customer) == [ActionKind.PAGE_MOVED]

    stranger = client.post(
        f"{URL}/{customer.id}/pages/{paid_for.id}/move",
        headers=support,
        json={"target": str(customer.id), "reason": "x"},
    )
    assert stranger.status_code == 404


def test_a_set_password_signs_the_customer_out(client: TestClient, db: Session) -> None:
    customer, _ = _shop(db)
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, root = _staff(db, Role.OWNER, email="root@office.test", superuser=True)
    signed_in = _bearer(customer)
    assert client.get("/api/v1/account", headers=signed_in).status_code == 200
    base = f"{URL}/{customer.id}/password"
    body = {
        "new_password1": "Tog'-Bahor-2026",
        "new_password2": "Tog'-Bahor-2026",
        "reason": "Akkaunt o'g'irlangan",
    }

    assert client.post(base, headers=owner, json=body).status_code == 404
    mismatch = client.post(base, headers=root, json=body | {"new_password2": "boshqa"})
    assert mismatch.status_code == 422
    weak = client.post(
        base,
        headers=root,
        json=body | {"new_password1": "12345678", "new_password2": "12345678"},
    )
    assert weak.status_code == 400

    done = client.post(base, headers=root, json=body)
    assert done.status_code == 200, done.text
    db.expire_all()
    stored = db.get(User, customer.id)
    assert stored is not None and check_password("Tog'-Bahor-2026", stored.password)
    assert client.get("/api/v1/account", headers=signed_in).status_code == 401
    assert _kinds(db, customer) == [ActionKind.PASSWORD_SET]


def test_deleting_a_customer_keeps_the_inviter_s_and_the_invitee_s_rows(
    client: TestClient, db: Session
) -> None:
    customer, plan = _shop(db)
    customer_id = customer.id
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    owner, headers = _staff(db, Role.OWNER, email="owner@office.test")
    invited = User(email="friend@client.test", password="!", date_joined=utcnow())
    db.add(invited)
    db.flush()
    db.add(ReferralBinding(owner_id=invited.id, referrer_id=customer.id, code="ABC"))
    db.add(
        Invoice(
            owner_id=customer.id,
            number="TA-0009",
            plan_id=plan.id,
            amount_minor=49000000,
            currency="UZS",
            period_days=30,
            expires_at=utcnow(),
            status=InvoiceStatus.PAID,
            paid_at=utcnow(),
        )
    )
    db.commit()
    assert client.get(f"{URL}/{customer.id}", headers=support).status_code == 200

    wrong = client.post(
        f"{URL}/{customer.id}/delete", headers=headers, json={"email": "other@x.test"}
    )
    assert wrong.status_code == 400
    gone = client.post(
        f"{URL}/{customer.id}/delete",
        headers=headers,
        json={"email": "SHOP@client.test "},
    )
    assert gone.status_code == 200, gone.text
    assert gone.json()["receipts_kept"] == 1

    db.expire_all()
    assert db.scalar(select(User.id).where(User.id == customer_id)) is None
    binding = db.scalar(
        select(ReferralBinding).where(ReferralBinding.owner_id == invited.id)
    )
    assert binding is not None and binding.referrer_id is None
    kept = db.scalar(select(Invoice).where(Invoice.number == "TA-0009"))
    assert kept is not None and kept.owner_id is None
    assert kept.former_email == "shop@client.test"
    assert _kinds(db, owner) == [ActionKind.ACCOUNT_PURGED]
