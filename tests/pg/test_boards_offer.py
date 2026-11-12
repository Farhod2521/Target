"""The sales manager's offer against PostgreSQL: «Chegirma berish» moves a
card to 20%, the minute sweep steps it to 10% and Chegirmasiz, and the
client's first plan bill is priced with it; a promo code comes off what is
left, and the wallet pays from the rest."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing import services as billing
from app.modules.billing.constants import InvoiceStatus, WalletChoice
from app.modules.billing.models import Invoice, Plan, PromoRedemption
from app.modules.billing.models.promo_code import PromoCode
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.referrals.constants import RewardStatus
from app.modules.referrals.models import ReferralReward
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import (
    URL,
    _client,
    _detail,
    _live,
    _paid,
    _plan,
    _sweep,
)
from tests.pg.test_crm_http import _auth

PRICE = 49_000_000  # 490 000 so'm in tiyin


def _offered(client: TestClient, db: Session, email: str) -> tuple[Any, dict[str, str]]:
    """A lead taken, talked to, and given the offer."""
    _live(db)
    owner = _client(db, email)
    _sweep(db)
    ali = _staff(db, f"ali.{email}", Role.SALES)
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))
    press = f"{URL}/cards/{card.id}/actions"
    talked = _detail(client.post(press, json={"action": "contacted"}, headers=ali))
    assert [a.value for a in talked.actions] == [
        "offer",
        "callback",
        "will_pay",
        "needs_support",
        "close",
        "release",
    ]
    given = _detail(client.post(press, json={"action": "offer"}, headers=ali))
    db.expire_all()
    return given, ali | {"owner": str(owner.id)}


def _age(db: Session, card_id: Any, *, hours: float) -> None:
    """The offer pressed ``hours`` ago."""
    db.execute(
        update(BoardCardEvent)
        .where(BoardCardEvent.card_id == card_id, BoardCardEvent.ref == "offered")
        .values(created_at=utcnow() - timedelta(hours=hours))
    )
    db.commit()


def _bill(db: Session, owner_id: str, *, promo: str = "") -> Invoice:
    owner = db.get(User, owner_id)
    assert owner is not None
    now = utcnow()
    invoice = billing.create_invoice(db, owner=owner, plan=_plan(db), now=now)
    priced = billing.price_invoice(
        db, invoice=invoice, promo_code=promo, wallet=WalletChoice.KEEP, now=now
    )
    db.commit()
    return priced


def test_the_offer_button_moves_the_card_to_20_once(
    client: TestClient, db: Session
) -> None:
    given, ali = _offered(client, db, "offer@shop.test")
    assert given.column == "discount_20"
    assert given.offer is not None and given.offer.percent == 20
    assert given.history[0].kind == "offered"
    assert [a.value for a in given.actions] == ["needs_support", "close"]

    press = f"{URL}/cards/{given.id}/actions"
    again = client.post(press, json={"action": "offer"}, headers=ali)
    assert again.status_code == 409

    boss = _staff(db, "boss@office.test", superuser=True)
    back = client.post(
        f"{URL}/cards/{given.id}/move",
        json={"column": "contacted", "reason": "sinov"},
        headers=boss,
    )
    assert back.status_code == 200, back.text
    twice = client.post(press, json={"action": "offer"}, headers=ali)
    assert twice.status_code == 409 and twice.json()["code"] == "offer_given"


def test_the_sweep_steps_the_offer_by_its_clock(
    client: TestClient, db: Session
) -> None:
    given, ali = _offered(client, db, "clock@shop.test")
    _sweep(db)
    assert db.get(BoardCard, given.id).column_code == "discount_20"  # type: ignore[union-attr]

    _age(db, given.id, hours=25)
    _sweep(db)
    db.expire_all()
    assert db.get(BoardCard, given.id).column_code == "discount_10"  # type: ignore[union-attr]
    shown = _detail(client.get(f"{URL}/cards/{given.id}", headers=ali))
    assert shown.offer is not None and shown.offer.percent == 10
    assert shown.history[0].kind == "offer_step"

    _sweep(db)
    db.expire_all()
    steps = db.scalars(
        select(BoardCardEvent.ref).where(BoardCardEvent.card_id == given.id)
    ).all()
    assert steps.count("discount_10") == 1

    _age(db, given.id, hours=73)
    _sweep(db)
    db.expire_all()
    assert db.get(BoardCard, given.id).column_code == "no_discount"  # type: ignore[union-attr]
    over = _detail(client.get(f"{URL}/cards/{given.id}", headers=ali))
    assert over.offer is not None and over.offer.percent == 0
    assert over.offer.ends_at is None


def test_the_columns_are_shown_after_bogxlanildi(
    client: TestClient, db: Session
) -> None:
    _live(db)
    lead = _staff(db, "lead@office.test", Role.SALES_LEAD)
    answer = client.get(f"{URL}/boards/sales/columns", headers=lead)
    codes = [c["code"] for c in answer.json()["columns"]]
    at = codes.index("contacted")
    assert codes[at + 1 : at + 5] == [
        "callback",
        "discount_20",
        "discount_10",
        "no_discount",
    ]
    assert "trial" not in codes


def test_the_first_bill_is_priced_with_the_offer(
    client: TestClient, db: Session
) -> None:
    given, ali = _offered(client, db, "bill@shop.test")
    bill = _bill(db, ali["owner"])
    assert bill.offer_minor == PRICE * 20 // 100
    assert bill.amount_minor == PRICE - bill.offer_minor
    assert bill.expires_at <= utcnow() + timedelta(hours=24, minutes=16)

    _age(db, given.id, hours=25)
    again = _bill(db, ali["owner"])
    assert again.id == bill.id
    assert again.offer_minor == PRICE * 10 // 100
    assert again.amount_minor == PRICE - again.offer_minor

    _age(db, given.id, hours=80)
    db.execute(
        update(Invoice)
        .where(Invoice.id == bill.id)
        .values(expires_at=utcnow() + timedelta(hours=1))
    )
    db.commit()
    over = _bill(db, ali["owner"])
    assert over.offer_minor == 0 and over.amount_minor == PRICE


def test_a_closed_card_or_a_paid_client_gets_no_offer(
    client: TestClient, db: Session
) -> None:
    given, ali = _offered(client, db, "closed@shop.test")
    press = f"{URL}/cards/{given.id}/actions"
    closed = client.post(
        press, json={"action": "close", "reason": "expensive"}, headers=ali
    )
    assert closed.status_code == 200, closed.text
    assert _bill(db, ali["owner"]).offer_minor == 0

    _other, staff = _offered(client, db, "paid@shop.test")
    owner = db.get(User, staff["owner"])
    assert owner is not None
    _paid(db, owner, status=InvoiceStatus.REFUNDED)
    assert _bill(db, staff["owner"]).offer_minor == 0


def _codes(db: Session) -> None:
    db.add_all(
        [
            PromoCode(
                code="BIG30",
                kind="discount",
                discount_kind="percent",
                discount_value=30,
            ),
            PromoCode(
                code="SMALL5",
                kind="discount",
                discount_kind="percent",
                discount_value=5,
            ),
        ]
    )
    db.commit()


def _redeemed(db: Session, bill: Invoice) -> PromoRedemption | None:
    return db.scalar(
        select(PromoRedemption).where(PromoRedemption.invoice_id == bill.id)
    )


def test_a_code_comes_off_what_the_offer_leaves(
    client: TestClient, db: Session
) -> None:
    _codes(db)
    given, ali = _offered(client, db, "promo@shop.test")
    after_offer = PRICE - PRICE * 20 // 100

    small = _bill(db, ali["owner"], promo="SMALL5")
    assert small.offer_minor == PRICE * 20 // 100
    assert small.amount_minor == after_offer - after_offer * 5 // 100
    redeemed = _redeemed(db, small)
    assert redeemed is not None and redeemed.discount_minor == after_offer * 5 // 100

    big = _bill(db, ali["owner"], promo="BIG30")
    assert big.offer_minor == PRICE * 20 // 100
    assert big.amount_minor == after_offer - after_offer * 30 // 100

    # The offer steps down: the same code is quoted again on the new base.
    _age(db, given.id, hours=25)
    stepped = _bill(db, ali["owner"], promo="BIG30")
    after_ten = PRICE - PRICE * 10 // 100
    assert stepped.offer_minor == PRICE * 10 // 100
    assert stepped.amount_minor == after_ten - after_ten * 30 // 100
    redeemed = _redeemed(db, stepped)
    assert redeemed is not None and redeemed.discount_minor == after_ten * 30 // 100

    back = _bill(db, ali["owner"])
    assert back.offer_minor == PRICE * 10 // 100
    assert back.amount_minor == after_ten
    assert _redeemed(db, back) is None


def test_the_wallet_pays_after_the_offer_and_the_code(
    client: TestClient, db: Session
) -> None:
    _codes(db)
    _given, ali = _offered(client, db, "purse@shop.test")
    owner = db.get(User, ali["owner"])
    assert owner is not None
    db.add(
        ReferralReward(
            owner_id=owner.id,
            base_minor=5_000_000,
            currency="UZS",
            amount_minor=1_000_000,
            status=RewardStatus.EARNED,
            earned_at=utcnow(),
        )
    )
    db.commit()
    now = utcnow()
    invoice = billing.create_invoice(db, owner=owner, plan=_plan(db), now=now)
    bill = billing.price_invoice(
        db, invoice=invoice, promo_code="SMALL5", wallet=WalletChoice.USE, now=now
    )
    db.commit()
    after_offer = PRICE - PRICE * 20 // 100
    after_code = after_offer - after_offer * 5 // 100
    assert bill.offer_minor == PRICE * 20 // 100
    assert bill.wallet_minor == 1_000_000
    assert bill.amount_minor == after_code - 1_000_000


def test_the_paywall_shows_the_offer_price(client: TestClient, db: Session) -> None:
    _given, ali = _offered(client, db, "wall@shop.test")
    owner = db.get(User, ali["owner"])
    assert owner is not None
    _plan(db)
    db.commit()
    shown = client.get(
        "/api/v1/billing/paywall", params={"plan": "standart"}, headers=_auth(owner)
    ).json()
    assert shown["sales_offer"]["percent"] == 20
    assert shown["chosen"]["discount_minor"] == PRICE * 20 // 100
    assert [c["offer"]["discount_minor"] for c in shown["cards"]] == [PRICE * 20 // 100]
    assert [c["offer"]["offer_minor"] for c in shown["cards"]] == [PRICE * 20 // 100]
    assert shown["chosen"]["price_minor"] == PRICE
    assert shown["chosen"]["promo_minor"] == 0


def test_the_paywall_takes_a_code_off_what_the_offer_leaves(
    client: TestClient, db: Session
) -> None:
    _codes(db)
    _given, ali = _offered(client, db, "wallcode@shop.test")
    owner = db.get(User, ali["owner"])
    assert owner is not None
    _plan(db)
    db.commit()
    shown = client.get(
        "/api/v1/billing/paywall",
        params={"plan": "standart", "promo": "SMALL5"},
        headers=_auth(owner),
    ).json()
    after_offer = PRICE - PRICE * 20 // 100
    promo = after_offer * 5 // 100
    assert shown["promo_quote"]["base_minor"] == after_offer
    assert shown["promo_quote"]["discount_minor"] == promo
    chosen = shown["chosen"]
    assert chosen["price_minor"] == PRICE
    assert chosen["offer_minor"] == PRICE * 20 // 100
    assert chosen["promo_minor"] == promo
    assert chosen["discount_minor"] == PRICE * 20 // 100 + promo
    assert chosen["due_minor"] == after_offer - promo

    # The bill comes out at the price the paywall showed.
    bill = _bill(db, ali["owner"], promo="SMALL5")
    assert bill.amount_minor == chosen["due_minor"]


START = 9_900_000  # 99 000 so'm in tiyin


def _start(db: Session, *, code: str = "start", one_time: bool = True) -> Plan:
    plan = Plan(
        code=code,
        name=code.title(),
        price=99000,
        currency="UZS",
        period_days=7,
        max_adsets=1,
        llm_cost_limit_minor=1000,
        is_one_time=one_time,
    )
    db.add(plan)
    db.flush()
    return plan


def test_start_is_never_discounted(client: TestClient, db: Session) -> None:
    _given, ali = _offered(client, db, "start@shop.test")
    owner = db.get(User, ali["owner"])
    assert owner is not None
    _plan(db)
    # Start by its code alone, and another plan by being one-time alone.
    start = _start(db, one_time=False)
    _start(db, code="proba")
    db.commit()
    shown = client.get(
        "/api/v1/billing/paywall", params={"plan": "start"}, headers=_auth(owner)
    ).json()
    assert shown["sales_offer"]["percent"] == 20
    taken = {c["code"]: c["offer"] for c in shown["cards"]}
    for code in ("start", "proba"):
        assert taken[code]["offer_minor"] == 0
        assert taken[code]["discount_minor"] == 0
        assert taken[code]["due_minor"] == START
    assert taken["standart"]["offer_minor"] == PRICE * 20 // 100
    assert shown["chosen"]["offer_minor"] == 0
    assert shown["chosen"]["due_minor"] == START

    now = utcnow()
    invoice = billing.create_invoice(db, owner=owner, plan=start, now=now)
    bill = billing.price_invoice(
        db, invoice=invoice, promo_code="", wallet=WalletChoice.KEEP, now=now
    )
    assert bill.offer_minor == 0 and bill.amount_minor == START
