"""The payments screen: who reads it, its lists, freeing a held bill, and the
hand command that takes a test payment out."""

import sys
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.backoffice.services.erase_payment import erase_payment, invoices_for
from app.modules.billing.constants import (
    InvoiceStatus,
    SubscriptionStatus,
    TransactionState,
)
from app.modules.billing.models import (
    Invoice,
    PaymentTransaction,
    Plan,
    PromoCode,
    PromoRedemption,
    Subscription,
    SubscriptionChange,
)
from app.modules.referrals.constants import RewardStatus
from app.modules.referrals.models import ReferralReward, WalletSpend
from app.modules.referrals.selectors import wallet_balance
from app.modules.sales.models import SalesCommission, SaleSource
from tests.pg.test_office_actions import _shop, _staff
from tools import erase_payment as erase_tool

URL = "/api/v1/office/payments"


def _bill(db: Session, plan: Plan, owner: User | None, number: str, **fields: object) -> Invoice:
    now = utcnow()
    bill = Invoice(
        owner_id=owner.id if owner else None,
        number=number,
        plan_id=plan.id,
        amount_minor=fields.pop("amount_minor", 490000),
        currency=fields.pop("currency", "UZS"),
        period_days=30,
        expires_at=now + timedelta(days=30),
        **fields,
    )
    db.add(bill)
    db.flush()
    return bill


def _attempt(db: Session, bill: Invoice, *, hours: int = 13, **fields: object) -> PaymentTransaction:
    attempt = PaymentTransaction(
        owner_id=bill.owner_id,
        invoice_id=bill.id,
        provider="payme",
        external_id=f"ext-{bill.number}",
        reference=f"ref-{bill.number}",
        state=fields.pop("state", TransactionState.CREATED),
        amount_minor=bill.amount_minor,
        currency=bill.currency,
        created_at=utcnow() - timedelta(hours=hours),
        **fields,
    )
    db.add(attempt)
    db.flush()
    return attempt


def test_only_the_owner_and_super_admin_read_it(client: TestClient, db: Session) -> None:
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, root = _staff(db, email="root@office.test", superuser=True)
    readers = (owner, root)
    others = [
        _staff(db, role, email=f"{role}@office.test")[1]
        for role in (Role.SUPPORT, Role.FINANCE, Role.ENGINEER, Role.SALES)
    ]
    for path in ("/summary", "/invoices", "/subscriptions"):
        for headers in readers:
            assert client.get(URL + path, headers=headers).status_code == 200
        for headers in others:
            assert client.get(URL + path, headers=headers).status_code == 404


def test_summary_keeps_currencies_apart(client: TestClient, db: Session) -> None:
    shop, plan = _shop(db)
    now = utcnow()
    _bill(db, plan, shop, "TA-1", status=InvoiceStatus.PAID, paid_at=now)
    _bill(db, plan, shop, "TA-2", status=InvoiceStatus.PAID, paid_at=now,
          amount_minor=1500, currency="USD")  # fmt: skip
    _bill(db, plan, shop, "TA-3", status=InvoiceStatus.PENDING, amount_minor=1000)
    held = _bill(db, plan, shop, "TA-4", status=InvoiceStatus.HELD, amount_minor=2000)
    attempt = _attempt(db, held)
    fresh = _bill(db, plan, shop, "TA-5", status=InvoiceStatus.HELD, amount_minor=3000)
    _attempt(db, fresh, hours=1)
    _bill(db, plan, shop, "TA-6", status=InvoiceStatus.REFUNDED)
    db.commit()
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")

    body = client.get(f"{URL}/summary", headers=owner).json()

    assert body["totals"]["earned"] == [
        {"currency": "USD", "amount_minor": 1500},
        {"currency": "UZS", "amount_minor": 490000},
    ]
    assert body["totals"]["unpaid"] == 3
    assert body["totals"]["unpaid_sums"] == [{"currency": "UZS", "amount_minor": 6000}]
    assert body["totals"]["refunded"] == 1
    assert body["totals"]["stuck"] == 1, "an attempt under 12 hours may still finish"
    assert [row["id"] for row in body["holds"]] == [str(attempt.id)]
    assert body["holds"][0]["email"] == "shop@client.test"
    assert [row["customer"]["email"] for row in body["running_out"]] == []


def test_invoice_list_filters_and_shows_the_transaction(
    client: TestClient, db: Session
) -> None:
    shop, plan = _shop(db)
    paid = _bill(db, plan, shop, "TA-11", status=InvoiceStatus.PAID, paid_at=utcnow())
    attempt = _attempt(db, paid, state=TransactionState.PERFORMED)
    _bill(db, plan, shop, "TA-12", status=InvoiceStatus.PENDING)
    _bill(db, plan, shop, "TA-13", status=InvoiceStatus.CANCELED)
    kept = _bill(db, plan, None, "TA-14", status=InvoiceStatus.PAID, paid_at=utcnow(),
                 former_email="gone@client.test", manual_method="cash")  # fmt: skip
    db.commit()
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")

    def numbers(**params: str) -> list[str]:
        seen = client.get(f"{URL}/invoices", headers=owner, params=params)
        assert seen.status_code == 200, seen.text
        return sorted(row["number"] for row in seen.json()["rows"])

    assert numbers() == ["TA-11", "TA-12", "TA-13", "TA-14"]
    assert numbers(state="open") == ["TA-12"]
    assert numbers(state="paid") == ["TA-11", "TA-14"]
    assert numbers(state="closed") == ["TA-13"]
    assert numbers(q="TA-12") == ["TA-12"]
    assert numbers(q="shop@client") == ["TA-11", "TA-12", "TA-13"]
    assert numbers(q="gone@client") == ["TA-14"], "a deleted account's receipt is found"

    rows = client.get(f"{URL}/invoices", headers=owner).json()["rows"]
    by_number = {row["number"]: row for row in rows}
    assert by_number["TA-11"]["transaction"]["id"] == str(attempt.id)
    assert by_number["TA-14"]["transaction"] is None
    assert by_number["TA-14"]["customer"] is None
    assert by_number["TA-14"]["email"] == "gone@client.test"
    assert kept.id is not None


def test_subscription_list_finds_who_never_paid(client: TestClient, db: Session) -> None:
    _, plan = _shop(db)
    other = User(email="paid@client.test", full_name="Paid", password="!",
                 date_joined=utcnow())  # fmt: skip
    db.add(other)
    db.flush()
    now = utcnow()
    db.add(Subscription(owner_id=other.id, plan_id=plan.id,
                        status=SubscriptionStatus.ACTIVE, started_at=now,
                        expires_at=now + timedelta(days=3)))  # fmt: skip
    _bill(db, plan, other, "TA-21", status=InvoiceStatus.PAID, paid_at=now)
    db.commit()
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")

    def emails(**params: str) -> list[str]:
        seen = client.get(f"{URL}/subscriptions", headers=owner, params=params)
        assert seen.status_code == 200, seen.text
        return [row["customer"]["email"] for row in seen.json()["rows"]]

    assert sorted(emails()) == ["paid@client.test", "shop@client.test"]
    assert emails(state="unpaid") == ["shop@client.test"]
    assert emails(q="paid@") == ["paid@client.test"]
    summary = client.get(f"{URL}/summary", headers=owner).json()
    assert [row["customer"]["email"] for row in summary["running_out"]] == [
        "paid@client.test"
    ]


def test_only_the_super_admin_frees_a_held_bill(client: TestClient, db: Session) -> None:
    shop, plan = _shop(db)
    held = _bill(db, plan, shop, "TA-31", status=InvoiceStatus.HELD)
    attempt = _attempt(db, held)
    db.commit()
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    root_user, root = _staff(db, email="root@office.test", superuser=True)
    path = f"{URL}/holds/{attempt.id}/release"

    assert client.post(path, headers=owner, json={"reason": "x"}).status_code == 404
    assert client.post(path, headers=finance, json={"reason": "x"}).status_code == 404
    db.expire_all()
    assert db.get(Invoice, held.id).status == InvoiceStatus.HELD

    assert client.post(path, headers=root, json={"reason": ""}).status_code == 422
    done = client.post(path, headers=root, json={"reason": "Mijoz qo'ng'iroq qildi"})
    assert done.status_code == 200, done.text

    db.expire_all()
    assert db.get(Invoice, held.id).status == InvoiceStatus.PENDING
    assert db.get(PaymentTransaction, attempt.id).state == TransactionState.CANCELED
    trace = db.scalar(
        select(StaffAction).where(StaffAction.kind == str(ActionKind.HOLD_RELEASED))
    )
    assert trace is not None and trace.owner_id == shop.id
    assert trace.actor_id == root_user.id
    assert trace.detail["invoice"] == "TA-31"
    assert client.post(path, headers=root, json={"reason": "x"}).status_code == 400


def _paid_test_bill(db: Session) -> tuple[User, User, Invoice, PaymentTransaction]:
    shop, plan = _shop(db)
    referrer = User(email="ref@client.test", full_name="Ref", password="!",
                    date_joined=utcnow())  # fmt: skip
    db.add(referrer)
    db.flush()
    now = utcnow()
    bill = _bill(db, plan, shop, "TA-41", status=InvoiceStatus.PAID, paid_at=now)
    attempt = _attempt(db, bill, state=TransactionState.PERFORMED)
    subscription = db.scalar(select(Subscription).where(Subscription.owner_id == shop.id))
    promo = PromoCode(code="TEST", kind="discount")
    db.add(promo)
    db.flush()
    db.add_all(
        [
            ReferralReward(owner_id=referrer.id, invoice_id=bill.id, base_minor=490000,
                           currency="UZS", amount_minor=98000,
                           status=RewardStatus.EARNED, earned_at=now),
            SalesCommission(owner_id=referrer.id, client_id=shop.id, invoice_id=bill.id,
                            base_minor=490000, percent=10, amount_minor=49000,
                            currency="UZS", earned_at=now),
            SaleSource(owner_id=shop.id, invoice_id=bill.id, source="self", paid_at=now),
            WalletSpend(owner_id=shop.id, invoice_id=bill.id, amount_minor=5000,
                        currency="UZS"),
            SubscriptionChange(owner_id=shop.id, subscription_id=subscription.id,
                               kind="paid", to_plan_id=plan.id, days=30,
                               expires_after=now + timedelta(days=30),
                               invoice_id=bill.id, occurred_at=now),
            PromoRedemption(owner_id=shop.id, promo_id=promo.id, invoice_id=bill.id,
                            redeemed_at=now),
        ]
    )  # fmt: skip
    db.commit()
    return shop, referrer, bill, attempt


def _left(db: Session, bill_id: object) -> int:
    return sum(
        db.scalar(select(func.count()).select_from(model).where(model.invoice_id == bill_id))
        for model in (
            PaymentTransaction, ReferralReward, SalesCommission, SaleSource,
            WalletSpend, SubscriptionChange, PromoRedemption,
        )
    )  # fmt: skip


def test_the_command_finds_a_bill_every_way(db: Session) -> None:
    _, _, bill, attempt = _paid_test_bill(db)
    for key in (str(attempt.id), attempt.external_id, attempt.reference, bill.number):
        assert [row.id for row in invoices_for(db, key=key)] == [bill.id]
        db.rollback()
    assert invoices_for(db, key="nothing") == []


def test_the_command_leaves_nothing_behind_and_commits_at_once(db: Session) -> None:
    shop, referrer, bill, _ = _paid_test_bill(db)
    bill_id = bill.id
    assert wallet_balance(db, owner=referrer)[0].earned_minor == 147000

    erased = erase_payment(db, invoice=bill)
    db.commit()

    assert (erased.number, erased.attempts) == ("TA-41", 1)
    assert (erased.rewards, erased.commissions, erased.wallet_spends) == (1, 1, 1)
    assert (erased.changes_unlinked, erased.promos_unlinked) == (1, 1)
    db.expire_all()
    assert db.get(Invoice, bill_id) is None
    assert _left(db, bill_id) == 0
    assert wallet_balance(db, owner=referrer) == ()
    assert db.scalar(select(func.count(SubscriptionChange.id))) == 1
    assert db.scalar(select(Subscription).where(Subscription.owner_id == shop.id))


def test_the_command_only_deletes_with_yes(
    db: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, bill, attempt = _paid_test_bill(db)
    bill_id = bill.id
    key = str(attempt.id)
    db.commit()
    monkeypatch.setattr(
        erase_tool,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False, autoflush=False),
    )

    monkeypatch.setattr(sys, "argv", ["erase_payment", key])
    assert erase_tool.main() == 0
    assert "Hech narsa o'zgarmadi" in capsys.readouterr().out
    db.rollback()
    db.expire_all()
    assert db.get(Invoice, bill_id) is not None
    assert _left(db, bill_id) == 7

    monkeypatch.setattr(sys, "argv", ["erase_payment", key, "--yes"])
    assert erase_tool.main() == 0
    assert "TA-41" in capsys.readouterr().out
    db.rollback()
    db.expire_all()
    assert db.get(Invoice, bill_id) is None
    assert _left(db, bill_id) == 0

    monkeypatch.setattr(sys, "argv", ["erase_payment", key, "--yes"])
    assert erase_tool.main() == 1
