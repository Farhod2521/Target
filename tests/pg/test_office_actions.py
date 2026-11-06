"""The writes on a customer's card, against PostgreSQL with Django's foreign keys."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import utcnow
from app.common.passwords import check_password
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.ads.models import DeliveryStop
from app.modules.audit.constants import EventName
from app.modules.audit.models import Event
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import (
    Invoice,
    Plan,
    Subscription,
    SubscriptionChange,
)
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    ProviderConnection,
)
from app.modules.referrals.models import (
    ReferralAccess,
    ReferralBinding,
    ReferralReward,
)
from app.modules.sales.models import SalesClaim, SalesCommission

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


def _plan_of(db: Session, customer: User) -> Subscription:
    subscription = db.scalar(
        select(Subscription).where(Subscription.owner_id == customer.id)
    )
    assert subscription is not None
    return subscription


def test_days_can_be_taken_back_and_no_money_moves(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    subscription = _plan_of(db, customer)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    base = f"{URL}/{customer.id}"
    before = subscription.expires_at
    bills = db.scalar(select(func.count()).select_from(Invoice))

    taken = client.post(
        f"{base}/days",
        headers=support,
        json={"days": 5, "take": True, "reason": "Xato berilgan"},
    )
    assert taken.status_code == 200, taken.text

    db.expire_all()
    assert subscription.expires_at == before - timedelta(days=5)
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.ended_at is None
    assert "-5" in subscription.note
    assert db.scalar(select(func.count()).select_from(Invoice)) == bills
    assert _kinds(db, customer) == [ActionKind.DAYS_TAKEN]
    change = db.scalar(
        select(SubscriptionChange).where(SubscriptionChange.owner_id == customer.id)
    )
    assert change is not None
    assert (change.kind, change.days) == ("taken", -5)
    assert change.expires_before == before
    assert db.scalar(
        select(Event).where(Event.name == EventName.SUBSCRIPTION_SHORTENED)
    )


def test_taking_every_day_left_ends_the_plan_only_when_asked(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    subscription = _plan_of(db, customer)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    base = f"{URL}/{customer.id}"
    before = subscription.expires_at
    asked = {"days": 25, "take": True, "reason": "Xato berilgan"}

    refused = client.post(f"{base}/days", headers=support, json=asked)
    assert refused.status_code == 400
    db.expire_all()
    assert subscription.expires_at == before
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert _kinds(db, customer) == []

    ended = client.post(
        f"{base}/days", headers=support, json={**asked, "may_end": True}
    )
    assert ended.status_code == 200, ended.text
    db.expire_all()
    assert subscription.status == SubscriptionStatus.EXPIRED
    assert subscription.ended_at is not None
    # The grace days count from here, so the end is never written before now.
    assert subscription.expires_at == subscription.ended_at

    again = client.post(f"{base}/days", headers=support, json={**asked, "days": 1})
    assert again.status_code == 400


def test_a_taken_day_writes_no_payment(client: TestClient, db: Session) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    refused = client.post(
        f"{URL}/{customer.id}/days",
        headers=support,
        json={"days": 1, "take": True, "paid": True, "amount": "100", "reason": "Xato"},
    )
    assert refused.status_code in (400, 422)
    assert _kinds(db, customer) == []


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


def test_a_page_s_pair_is_changed_and_removed_by_meta_ids(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    link = ProviderConnection(
        owner_id=customer.id, provider="meta", token_encrypted=b"x", status="active"
    )
    db.add(link)
    db.flush()
    page = PageAccount(
        owner_id=customer.id,
        provider="meta",
        external_id="p1",
        connection_id=link.id,
        token_encrypted=b"x",
        is_active=True,
        is_current=True,
    )
    first, second = (
        AdAccount(
            owner_id=customer.id,
            provider="meta",
            external_id=external_id,
            connection_id=link.id,
            is_active=True,
        )
        for external_id in ("act_1", "act_2")
    )
    db.add_all([page, first, second])
    db.flush()
    db.add(PagePair(owner_id=customer.id, page_id=page.id, ad_account_id=first.id))
    db.commit()
    base = f"{URL}/{customer.id}/pages/{page.id}"

    changed = client.post(
        f"{base}/account",
        headers=support,
        json={"current": "act_1", "target": "act_2", "reason": "Filial"},
    )
    assert changed.status_code == 200, changed.text
    db.expire_all()
    pair = db.scalar(select(PagePair).where(PagePair.page_id == page.id))
    assert pair is not None and pair.ad_account_id == second.id

    removed = client.post(
        f"{base}/remove-pair",
        headers=support,
        json={"account": "act_2", "reason": "Xato"},
    )
    assert removed.status_code == 200, removed.text
    db.expire_all()
    assert db.scalar(select(PagePair).where(PagePair.page_id == page.id)) is None
    assert _kinds(db, customer) == [
        ActionKind.PAGE_ACCOUNT_CHANGED,
        ActionKind.PAGE_PAIR_REMOVED,
    ]


def test_blocking_a_customer_stops_their_crm_logins_too(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    login = User(
        email="manager@client.test",
        password="!",
        date_joined=utcnow(),
        crm_owner_id=customer.id,
    )
    db.add(login)
    db.commit()
    member = _bearer(login)
    base = f"{URL}/{customer.id}"
    assert client.get("/api/v1/crm/nav", headers=member).status_code == 200

    blocked = client.post(f"{base}/block", headers=support, json={"reason": "Firibgar"})
    assert blocked.status_code == 200, blocked.text
    assert client.get("/api/v1/crm/nav", headers=member).status_code == 401

    freed = client.post(
        f"{base}/unblock", headers=support, json={"reason": "Tekshirildi"}
    )
    assert freed.status_code == 200, freed.text
    assert client.get("/api/v1/crm/nav", headers=member).status_code == 200


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


def test_deleting_a_customer_others_earned_from_keeps_their_money(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    customer_id = customer.id
    owner, headers = _staff(db, Role.OWNER, email="owner@office.test")
    seller, _ = _staff(db, Role.SALES, email="seller@office.test")
    inviter = User(email="inviter@client.test", password="!", date_joined=utcnow())
    db.add(inviter)
    db.flush()
    link = ProviderConnection(
        owner_id=customer.id, provider="meta", token_encrypted=b"x", status="active"
    )
    db.add(link)
    db.flush()
    account = AdAccount(
        owner_id=customer.id,
        provider="meta",
        external_id="act_1",
        connection_id=link.id,
    )
    db.add(account)
    db.flush()
    binding = ReferralBinding(owner_id=customer.id, referrer_id=inviter.id, code="ABC")
    claim = SalesClaim(
        owner_id=customer.id,
        manager_id=seller.id,
        claimed_at=utcnow(),
        expires_at=utcnow(),
    )
    db.add_all(
        [
            binding,
            claim,
            DeliveryStop(
                owner_id=customer.id,
                ad_account_id=account.id,
                level="campaign",
                external_id="c1",
                reason="spend_cap",
                detected_at=utcnow(),
            ),
        ]
    )
    db.flush()
    reward = ReferralReward(
        owner_id=inviter.id,
        binding_id=binding.id,
        base_minor=100,
        amount_minor=10,
        earned_at=utcnow(),
    )
    commission = SalesCommission(
        owner_id=seller.id,
        client_id=customer.id,
        claim_id=claim.id,
        base_minor=100,
        percent=10,
        amount_minor=10,
        earned_at=utcnow(),
    )
    db.add_all([reward, commission])
    db.commit()

    gone = client.post(
        f"{URL}/{customer.id}/delete", headers=headers, json={"email": customer.email}
    )
    assert gone.status_code == 200, gone.text

    db.expire_all()
    assert db.scalar(select(User.id).where(User.id == customer_id)) is None
    assert db.scalar(select(DeliveryStop.id)) is None
    kept_reward = db.get(ReferralReward, reward.id)
    assert kept_reward is not None and kept_reward.binding_id is None
    kept_commission = db.get(SalesCommission, commission.id)
    assert kept_commission is not None
    assert kept_commission.claim_id is None and kept_commission.client_id is None
    assert _kinds(db, owner) == [ActionKind.ACCOUNT_PURGED]


def test_blocking_signs_the_customer_out_until_unblocked(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, finance = _staff(db, Role.FINANCE, email="money@office.test")
    signed_in = _bearer(customer)
    base = f"{URL}/{customer.id}"

    assert (
        client.post(f"{base}/block", headers=finance, json={"reason": "x"}).status_code
        == 404
    )
    assert client.post(f"{base}/block", headers=support, json={}).status_code == 422
    not_yet = client.post(f"{base}/unblock", headers=support, json={"reason": "x"})
    assert not_yet.status_code == 400

    blocked = client.post(f"{base}/block", headers=support, json={"reason": "Firibgar"})
    assert blocked.status_code == 200, blocked.text
    assert blocked.json() == {"message": "Akkaunt bloklandi."}
    assert client.get("/api/v1/account", headers=signed_in).status_code == 401
    assert client.get(base, headers=support).json()["profile"]["is_blocked"] is True
    again = client.post(f"{base}/block", headers=support, json={"reason": "x"})
    assert again.status_code == 400

    freed = client.post(
        f"{base}/unblock", headers=support, json={"reason": "Tekshirildi"}
    )
    assert freed.status_code == 200, freed.text
    assert client.get(base, headers=support).json()["profile"]["is_blocked"] is False
    assert client.get("/api/v1/account", headers=_bearer(customer)).status_code == 200

    db.expire_all()
    assert [kind for kind in _kinds(db, customer) if kind != ActionKind.VIEW] == [
        ActionKind.ACCOUNT_BLOCKED,
        ActionKind.ACCOUNT_UNBLOCKED,
    ]
    assert list(
        db.scalars(
            select(Event.name)
            .where(
                Event.owner_id == customer.id,
                Event.name.in_([EventName.USER_BLOCKED, EventName.USER_UNBLOCKED]),
            )
            .order_by(Event.occurred_at)
        )
    ) == [EventName.USER_BLOCKED, EventName.USER_UNBLOCKED]


def test_a_colleagues_account_is_run_here_but_its_door_and_money_are_not(
    client: TestClient, db: Session
) -> None:
    _shop(db, subscribed=False)
    tester, _ = _staff(db, Role.SALES, email="tester@office.test")
    _, root = _staff(db, Role.OWNER, email="root@office.test", superuser=True)
    base = f"{URL}/{tester.id}"
    paid = {"paid": True, "amount": "100", "method": "cash"}

    card = client.get(base, headers=root)
    assert card.status_code == 200, card.text
    assert card.json()["profile"]["is_staff"] is True
    given = client.post(
        f"{base}/plan", headers=root, json={"plan": "pro", "reason": "Sinov"}
    )
    assert given.status_code == 200, given.text
    more = client.post(
        f"{base}/days", headers=root, json={"days": 3, "reason": "Sinov"}
    )
    assert more.status_code == 200, more.text

    refused = {
        "plan": client.post(
            f"{base}/plan", headers=root, json={"plan": "pro", "reason": "x", **paid}
        ),
        "days": client.post(
            f"{base}/days", headers=root, json={"days": 1, "reason": "x", **paid}
        ),
        "slots": client.post(
            f"{base}/slots", headers=root, json={"pages": 1, "reason": "x", **paid}
        ),
        "payment": client.post(
            f"{base}/payment",
            headers=root,
            json={"amount": "100", "method": "cash", "reason": "x"},
        ),
        "payout": client.post(
            f"{base}/payout",
            headers=root,
            json={"amount": "1", "currency": "UZS", "method": "cash", "reason": "x"},
        ),
        "password": client.post(
            f"{base}/password",
            headers=root,
            json={
                "new_password1": "Xx12345678!",
                "new_password2": "Xx12345678!",
                "reason": "x",
            },
        ),
        "block": client.post(f"{base}/block", headers=root, json={"reason": "x"}),
        "unblock": client.post(f"{base}/unblock", headers=root, json={"reason": "x"}),
        "delete": client.post(
            f"{base}/delete", headers=root, json={"email": "tester@office.test"}
        ),
    }
    assert {name: r.status_code for name, r in refused.items()} == dict.fromkeys(
        refused, 403
    ), {name: r.text for name, r in refused.items()}
    assert {r.json()["code"] for r in refused.values()} == {"staff_account"}

    db.expire_all()
    still = db.get(User, tester.id)
    assert still is not None and still.is_active and still.is_staff
    assert db.scalar(select(Invoice).where(Invoice.owner_id == tester.id)) is None
