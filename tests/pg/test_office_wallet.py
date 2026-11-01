"""The Hamyon screen: who reads what, the queue, its answers and their refusals."""

from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import encrypt
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.backoffice.selectors.wallet import is_overdue
from app.modules.businesses.models import Business
from app.modules.referrals.constants import PayoutMethod, PayoutStatus, RewardStatus
from app.modules.referrals.models import ReferralReward, WithdrawalRequest
from app.modules.referrals.selectors import available_minor
from tests.pg.test_office_actions import _shop, _staff

URL = "/api/v1/office/wallet"
CARD = "8600123456784417"


@pytest.fixture(autouse=True)
def card_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "withdrawals_open", True)


def _earned(db: Session, owner: User, amount_minor: int = 500000) -> None:
    db.add(
        ReferralReward(
            owner_id=owner.id,
            base_minor=amount_minor * 5,
            currency="UZS",
            amount_minor=amount_minor,
            status=RewardStatus.EARNED,
            earned_at=utcnow(),
        )
    )
    db.commit()


def _ask(db: Session, owner: User, **fields: object) -> WithdrawalRequest:
    ask = WithdrawalRequest(
        owner_id=owner.id,
        amount_minor=fields.pop("amount_minor", 174000),
        currency=fields.pop("currency", "UZS"),
        method=PayoutMethod.CARD,
        status=fields.pop("status", PayoutStatus.REQUESTED),
        card_number_encrypted=encrypt(CARD),
        card_last4=CARD[-4:],
        card_holder="AZIZA OLIMOVA",
        **fields,
    )
    db.add(ask)
    db.commit()
    return ask


def _customer(db: Session, email: str) -> User:
    person = User(email=email, full_name=email, password="!", date_joined=utcnow())
    db.add(person)
    db.commit()
    return person


def _kinds(db: Session, owner: User) -> list[str]:
    return list(
        db.scalars(select(StaffAction.kind).where(StaffAction.owner_id == owner.id))
    )


@pytest.mark.parametrize("role", [Role.ENGINEER, Role.SALES])
def test_a_role_outside_the_money_gets_a_missing_page(
    client: TestClient, db: Session, role: Role
) -> None:
    _, headers = _staff(db, role, email="other@office.test")
    shop, _ = _shop(db)
    ask = _ask(db, shop)

    assert client.get(f"{URL}/queue", headers=headers).status_code == 404
    assert client.get(f"{URL}/history", headers=headers).status_code == 404
    refused = client.post(f"{URL}/{ask.id}/paid", headers=headers, json={})
    assert refused.status_code == 404


def test_a_customer_gets_a_missing_page(client: TestClient, db: Session) -> None:
    from tests.pg.test_office_actions import _bearer

    shop, _ = _shop(db)
    assert client.get(f"{URL}/queue", headers=_bearer(shop)).status_code == 404


def test_support_reads_the_queue_without_the_card_and_cannot_answer(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.SUPPORT, email="support@office.test")
    shop, _ = _shop(db)
    ask = _ask(db, shop)

    body = client.get(f"{URL}/queue", headers=headers).json()

    assert body["can_act"] is False
    row = body["rows"][0]
    assert row["card_number"] is None and row["card_holder"] is None
    assert row["card_last4"] == "4417"
    for answer, payload in (("paid", {}), ("reject", {"reason": "x"})):
        refused = client.post(f"{URL}/{ask.id}/{answer}", headers=headers, json=payload)
        assert refused.status_code == 404
    db.expire_all()
    assert db.get(WithdrawalRequest, ask.id).status == PayoutStatus.REQUESTED


def test_finance_reads_the_whole_card_oldest_first_and_totals_by_currency(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.FINANCE, email="finance@office.test")
    shop, _ = _shop(db)
    other = _customer(db, "other@client.test")
    third = _customer(db, "third@client.test")
    db.add(Business(user_id=shop.id, name="Shop Ltd", timezone="Asia/Tashkent"))
    db.commit()
    now = utcnow()
    _ask(db, other, amount_minor=100, created_at=now - timedelta(hours=1))
    _ask(db, shop, amount_minor=200, created_at=now - timedelta(hours=50))
    _ask(db, third, amount_minor=300, currency="USD", created_at=now)

    body = client.get(f"{URL}/queue", headers=headers).json()

    assert body["can_act"] is True
    assert [row["customer"]["email"] for row in body["rows"]] == [
        shop.email,
        other.email,
        third.email,
    ]
    first = body["rows"][0]
    assert first["card_number"] == "8600 1234 5678 4417"
    assert first["card_holder"] == "AZIZA OLIMOVA"
    assert first["customer"]["business"] == "Shop Ltd"
    assert [row["overdue"] for row in body["rows"]] == [True, False, False]
    assert body["totals"] == [
        {"currency": "USD", "amount_minor": 300},
        {"currency": "UZS", "amount_minor": 300},
    ]


def test_overdue_starts_at_forty_eight_hours() -> None:
    now = utcnow()
    ask = WithdrawalRequest(created_at=now - timedelta(hours=48))
    assert is_overdue(ask, now=now) is True
    ask.created_at = now - timedelta(hours=47, minutes=59)
    assert is_overdue(ask, now=now) is False


def test_paying_closes_the_ask_notes_the_journal_and_leaves_the_queue(
    client: TestClient, db: Session
) -> None:
    member, headers = _staff(db, Role.FINANCE, email="finance@office.test")
    shop, _ = _shop(db)
    _earned(db, shop)
    ask = _ask(db, shop)

    paid = client.post(
        f"{URL}/{ask.id}/paid", headers=headers, json={"pay_reference": " 448120 "}
    )

    assert paid.status_code == 200, paid.text
    assert paid.json() == {"message": "To'lov qayd etildi."}
    db.expire_all()
    row = db.get(WithdrawalRequest, ask.id)
    assert row.status == PayoutStatus.PAID and row.pay_reference == "448120"
    assert row.decided_by_id == member.id and row.decided_at is not None
    assert available_minor(db, owner=shop, currency="UZS") == 500000 - 174000
    assert _kinds(db, shop) == [ActionKind.WITHDRAWAL_PAID]
    assert client.get(f"{URL}/queue", headers=headers).json()["rows"] == []


def test_an_ask_is_answered_once(client: TestClient, db: Session) -> None:
    _, headers = _staff(db, Role.FINANCE, email="finance@office.test")
    shop, _ = _shop(db)
    _earned(db, shop)
    ask = _ask(db, shop)
    assert (
        client.post(f"{URL}/{ask.id}/paid", headers=headers, json={}).status_code == 200
    )

    again = client.post(f"{URL}/{ask.id}/paid", headers=headers, json={})
    refused = client.post(f"{URL}/{ask.id}/reject", headers=headers, json={"reason": "x"})

    for answer in (again, refused):
        assert answer.status_code == 400, answer.text
        assert answer.json()["detail"] == "Bu so'rovga allaqachon javob berilgan."
    assert _kinds(db, shop) == [ActionKind.WITHDRAWAL_PAID]


def test_an_ask_above_the_balance_is_not_paid(client: TestClient, db: Session) -> None:
    _, headers = _staff(db, Role.FINANCE, email="finance@office.test")
    shop, _ = _shop(db)
    _earned(db, shop, amount_minor=1000)
    ask = _ask(db, shop, amount_minor=174000)

    refused = client.post(f"{URL}/{ask.id}/paid", headers=headers, json={})

    assert refused.status_code == 400, refused.text
    db.expire_all()
    assert db.get(WithdrawalRequest, ask.id).status == PayoutStatus.REQUESTED
    assert _kinds(db, shop) == []


def test_turning_down_keeps_the_reason_and_gives_the_balance_back(
    client: TestClient, db: Session
) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    _earned(db, shop)
    ask = _ask(db, shop)
    assert available_minor(db, owner=shop, currency="UZS") == 500000 - 174000

    answer = client.post(
        f"{URL}/{ask.id}/reject", headers=headers, json={"reason": "Karta noto'g'ri"}
    )

    assert answer.status_code == 200, answer.text
    db.expire_all()
    row = db.get(WithdrawalRequest, ask.id)
    assert row.status == PayoutStatus.REJECTED
    assert row.reject_reason == "Karta noto'g'ri"
    assert available_minor(db, owner=shop, currency="UZS") == 500000
    assert _kinds(db, shop) == [ActionKind.WITHDRAWAL_REJECTED]


@pytest.mark.parametrize("answer", ["reject", "void"])
@pytest.mark.parametrize("reason", ["", "   "])
def test_a_reason_is_required(
    client: TestClient, db: Session, answer: str, reason: str
) -> None:
    _, headers = _staff(db, Role.FINANCE, email="finance@office.test")
    shop, _ = _shop(db)
    status = PayoutStatus.REQUESTED if answer == "reject" else PayoutStatus.PAID
    ask = _ask(db, shop, status=status)

    refused = client.post(
        f"{URL}/{ask.id}/{answer}", headers=headers, json={"reason": reason}
    )

    assert refused.status_code in {400, 422}, refused.text
    db.expire_all()
    assert db.get(WithdrawalRequest, ask.id).status == status
    assert _kinds(db, shop) == []


def test_voiding_a_payout_returns_its_money_and_only_a_paid_row_voids(
    client: TestClient, db: Session
) -> None:
    member, headers = _staff(db, Role.FINANCE, email="finance@office.test")
    shop, _ = _shop(db)
    _earned(db, shop)
    ask = _ask(db, shop)

    waiting = client.post(f"{URL}/{ask.id}/void", headers=headers, json={"reason": "x"})
    assert waiting.status_code == 400
    assert waiting.json()["detail"] == "Faqat to'langan yozuvni bekor qilish mumkin."

    client.post(f"{URL}/{ask.id}/paid", headers=headers, json={})
    voided = client.post(
        f"{URL}/{ask.id}/void", headers=headers, json={"reason": "Bankdan qaytdi"}
    )
    assert voided.status_code == 200, voided.text
    db.expire_all()
    row = db.get(WithdrawalRequest, ask.id)
    assert row.status == PayoutStatus.VOIDED and row.voided_by_id == member.id
    assert available_minor(db, owner=shop, currency="UZS") == 500000

    again = client.post(f"{URL}/{ask.id}/void", headers=headers, json={"reason": "x"})
    assert again.status_code == 400
    assert again.json()["detail"] == "Bu yozuv allaqachon bekor qilingan."
    assert sorted(_kinds(db, shop)) == sorted(
        [ActionKind.WITHDRAWAL_PAID, ActionKind.WITHDRAWAL_VOIDED]
    )


@pytest.mark.parametrize("answer", ["paid", "reject", "void"])
def test_an_unknown_payout_is_a_missing_page(
    client: TestClient, db: Session, answer: str
) -> None:
    _, headers = _staff(db, Role.FINANCE, email="finance@office.test")
    missing = "00000000-0000-0000-0000-000000000000"
    body = {} if answer == "paid" else {"reason": "x"}
    reply = client.post(f"{URL}/{missing}/{answer}", headers=headers, json=body)
    assert reply.status_code == 404


def test_history_filters_searches_counts_and_names_who_answered(
    client: TestClient, db: Session
) -> None:
    member, headers = _staff(db, Role.SUPPORT, email="support@office.test")
    shop, _ = _shop(db)
    other = _customer(db, "other@client.test")
    now = utcnow()
    paid = _ask(
        db,
        shop,
        status=PayoutStatus.PAID,
        pay_reference="448120",
        decided_by_id=member.id,
        decided_at=now,
        created_at=now - timedelta(hours=2),
    )
    _ask(
        db,
        other,
        status=PayoutStatus.REJECTED,
        reject_reason="Karta noto'g'ri",
        decided_by_id=member.id,
        decided_at=now,
    )
    _ask(
        db,
        other,
        status=PayoutStatus.VOIDED,
        void_reason="Bankdan qaytdi",
        decided_by_id=None,
        voided_by_id=member.id,
        voided_at=now,
        created_at=now - timedelta(hours=1),
    )
    _ask(db, other)

    whole = client.get(f"{URL}/history", headers=headers).json()
    assert [row["status"] for row in whole["rows"]] == ["rejected", "voided", "paid"]
    assert whole["total"] == 3 and whole["has_more"] is False
    assert whole["counts"] == {"paid": 1, "rejected": 1, "voided": 1}
    assert [row["reason"] for row in whole["rows"]] == [
        "Karta noto'g'ri",
        "Bankdan qaytdi",
        "",
    ]
    assert all(row["by"]["id"] == str(member.id) for row in whole["rows"])
    assert whole["rows"][2]["id"] == str(paid.id)
    assert whole["rows"][2]["pay_reference"] == "448120"

    chip = client.get(f"{URL}/history?state=paid", headers=headers).json()
    assert [row["id"] for row in chip["rows"]] == [str(paid.id)]
    assert chip["total"] == 1 and chip["counts"]["voided"] == 1

    for term in ("448120", "shop@client", "4417"):
        found = client.get(
            f"{URL}/history", headers=headers, params={"q": term}
        ).json()
        assert str(paid.id) in [row["id"] for row in found["rows"]], term
    assert client.get(
        f"{URL}/history", headers=headers, params={"q": "shop@client"}
    ).json()["counts"] == {"paid": 1}
    assert client.get(
        f"{URL}/history", headers=headers, params={"q": "nobody"}
    ).json()["rows"] == []
    assert not any(
        "card_number" in row or "card_holder" in row for row in whole["rows"]
    )


def test_history_pages_by_offset(client: TestClient, db: Session) -> None:
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, _ = _shop(db)
    now = utcnow()
    db.add_all(
        WithdrawalRequest(
            owner_id=shop.id,
            amount_minor=1,
            currency="UZS",
            method=PayoutMethod.CARD,
            status=PayoutStatus.PAID,
            card_number_encrypted=b"",
            created_at=now - timedelta(minutes=index),
        )
        for index in range(52)
    )
    db.commit()

    first = client.get(f"{URL}/history", headers=headers).json()
    assert len(first["rows"]) == 50 and first["has_more"] is True
    second = client.get(
        f"{URL}/history?offset={first['next_offset']}", headers=headers
    ).json()
    assert len(second["rows"]) == 2 and second["has_more"] is False
    assert db.scalar(select(func.count(WithdrawalRequest.id))) == 52


def test_a_payout_recorded_by_hand_shows_in_the_history(
    client: TestClient, db: Session
) -> None:
    from app.modules.billing.constants import InvoiceStatus
    from tests.pg.test_office_payments import _bill

    _, headers = _staff(db, Role.FINANCE, email="finance@office.test")
    shop, plan = _shop(db)
    _bill(db, plan, shop, "TA-1", status=InvoiceStatus.PAID, paid_at=utcnow())
    db.commit()
    _earned(db, shop)

    recorded = client.post(
        f"/api/v1/office/customers/{shop.id}/payout",
        headers=headers,
        json={
            "reason": "Naqd berildi",
            "amount": "1000",
            "currency": "UZS",
            "method": "cash",
        },
    )

    assert recorded.status_code == 200, recorded.text
    row = client.get(f"{URL}/history", headers=headers).json()["rows"][0]
    assert row["method_label"] == "Naqd" and row["card_last4"] == ""


@pytest.mark.parametrize(
    ("role", "sections"),
    [
        (Role.SUPPORT, ["home", "clients", "promo", "payouts", "reviews", "surveys", "chat", "refusals"]),
        (Role.FINANCE, ["home", "clients", "promo", "payouts", "reviews", "surveys", "refusals"]),
        (
            Role.OWNER,
            [
                "home",
                "clients",
                "payments",
                "promo",
                "payouts",
                "reviews",
                "surveys",
                "sales",
                "chat",
                "refusals",
            ],
        ),
        (Role.SALES, ["sales", "refusals"]),
        (Role.ENGINEER, ["refusals"]),
    ],
)
def test_the_rail_names_only_the_doors_this_role_opens(
    client: TestClient, db: Session, role: Role, sections: list[str]
) -> None:
    _, headers = _staff(db, role, email="member@office.test")
    assert client.get("/api/v1/office/me", headers=headers).json()["sections"] == sections


def test_closed_withdrawals_leave_the_rail_and_refuse_a_payout_by_hand(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.billing.constants import InvoiceStatus
    from tests.pg.test_office_payments import _bill

    monkeypatch.setattr(settings, "withdrawals_open", False)
    _, headers = _staff(db, Role.OWNER, email="owner@office.test")
    shop, plan = _shop(db)
    _bill(db, plan, shop, "TA-1", status=InvoiceStatus.PAID, paid_at=utcnow())
    db.commit()
    _earned(db, shop)

    me = client.get("/api/v1/office/me", headers=headers).json()
    assert "payouts" not in me["sections"]
    card = client.get(f"/api/v1/office/customers/{shop.id}", headers=headers).json()
    assert card["referral"]["wallet_payable"] is False

    refused = client.post(
        f"/api/v1/office/customers/{shop.id}/payout",
        headers=headers,
        json={"reason": "x", "amount": "1000", "currency": "UZS", "method": "cash"},
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "withdrawals_closed"
    assert db.scalar(select(func.count(WithdrawalRequest.id))) == 0
    assert available_minor(db, owner=shop, currency="UZS") == 500000
