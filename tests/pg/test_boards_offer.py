"""The Sales discount against PostgreSQL. It starts on its own: when the
manager presses «Gaplashildi» on a lead, or when the client pays Start. 20%
for a day, 10% for three more, then the card closes. The percent is taken
off the plan's price less the unused Start days; a promo code comes off what
is left, and the wallet pays from the rest."""

from datetime import datetime, timedelta
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
from app.modules.billing.services import apply_payment
from app.modules.boards import triggers
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
DISCOUNT_BUTTONS = ["contacted", "no_contact", "callback", "needs_support", "close"]


def _offered(client: TestClient, db: Session, email: str) -> tuple[Any, dict[str, str]]:
    """A lead taken and talked to: the talk starts the discount."""
    _live(db)
    owner = _client(db, email)
    _sweep(db)
    ali = _staff(db, f"ali.{email}", Role.SALES)
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))
    press = f"{URL}/cards/{card.id}/actions"
    given = _detail(client.post(press, json={"action": "contacted"}, headers=ali))
    assert [a.value for a in given.actions] == DISCOUNT_BUTTONS
    db.expire_all()
    return given, ali | {"owner": str(owner.id)}


def _age(db: Session, card_id: Any, *, hours: float) -> None:
    """The talk was ``hours`` ago."""
    db.execute(
        update(BoardCardEvent)
        .where(BoardCardEvent.card_id == card_id, BoardCardEvent.ref == "offered")
        .values(created_at=utcnow() - timedelta(hours=hours))
    )
    db.commit()


def _bill(db: Session, owner_id: Any, *, promo: str = "") -> Invoice:
    owner = db.get(User, owner_id)
    assert owner is not None
    now = utcnow()
    invoice = billing.create_invoice(db, owner=owner, plan=_plan(db), now=now)
    priced = billing.price_invoice(
        db, invoice=invoice, promo_code=promo, wallet=WalletChoice.KEEP, now=now
    )
    db.commit()
    return priced


def _column(db: Session, card_id: Any) -> str:
    db.expire_all()
    card = db.get(BoardCard, card_id)
    assert card is not None
    return card.column_code


def test_gaplashildi_starts_the_discount_once(client: TestClient, db: Session) -> None:
    given, ali = _offered(client, db, "offer@shop.test")
    assert given.column == "discount_20"
    assert given.offer is not None and given.offer.percent == 20
    assert given.offer.source == "contact"
    assert given.offer.next_percent == 10 and given.offer.next_ends_at is not None
    assert given.offer.next_ends_at - given.offer.started_at == timedelta(hours=96)
    assert given.history[0].kind == "offered"

    # Moved out by hand and talked to again: no second discount, same clock.
    boss = _staff(db, "boss@office.test", superuser=True)
    back = client.post(
        f"{URL}/cards/{given.id}/move",
        json={"column": "no_contact", "reason": "sinov"},
        headers=boss,
    )
    assert back.status_code == 200, back.text
    press = f"{URL}/cards/{given.id}/actions"
    again = _detail(client.post(press, json={"action": "contacted"}, headers=ali))
    assert again.column == "contacted"
    assert [h.kind for h in again.history].count("offered") == 1
    assert again.offer is not None
    assert again.offer.started_at == given.offer.started_at
    # The price does not read the column: the discount still runs.
    assert _bill(db, ali["owner"]).offer_minor == PRICE * 20 // 100


def test_the_sweep_steps_the_discount_and_closes_the_card(
    client: TestClient, db: Session
) -> None:
    given, ali = _offered(client, db, "clock@shop.test")
    _sweep(db)
    assert _column(db, given.id) == "discount_20"

    _age(db, given.id, hours=25)
    _sweep(db)
    assert _column(db, given.id) == "discount_10"
    shown = _detail(client.get(f"{URL}/cards/{given.id}", headers=ali))
    assert shown.offer is not None and shown.offer.percent == 10
    assert shown.offer.next_percent == 0 and shown.offer.next_ends_at is None
    assert shown.history[0].kind == "offer_step"

    _sweep(db)
    db.expire_all()
    steps = db.scalars(
        select(BoardCardEvent.ref).where(BoardCardEvent.card_id == given.id)
    ).all()
    assert steps.count("discount_10") == 1

    # 10% lasts three days after the first: still on at hour 95.
    _age(db, given.id, hours=95)
    _sweep(db)
    assert _column(db, given.id) == "discount_10"

    _age(db, given.id, hours=97)
    _sweep(db)
    assert _column(db, given.id) == "closed"
    over = _detail(client.get(f"{URL}/cards/{given.id}", headers=ali))
    assert over.closed_at is not None and over.close_reason == "offer_ended"
    assert over.close_reason_label == "Chegirma tugadi"
    assert over.history[0].kind == "offer_ended" and over.actions == []
    assert over.offer is not None and over.offer.percent == 0
    assert over.offer.ends_at is None
    assert _sweep(db) == (0, 0)


def test_the_discount_columns_are_shown_and_chegirmasiz_is_not(
    client: TestClient, db: Session
) -> None:
    _live(db)
    lead = _staff(db, "lead@office.test", Role.SALES_LEAD)
    answer = client.get(f"{URL}/boards/sales/columns", headers=lead)
    codes = [c["code"] for c in answer.json()["columns"]]
    at = codes.index("contacted")
    assert codes[at + 1 : at + 4] == ["callback", "discount_20", "discount_10"]
    assert "trial" not in codes and "no_discount" not in codes


def test_the_first_bill_is_priced_with_the_discount(
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
    still = _bill(db, ali["owner"])
    assert still.offer_minor == PRICE * 10 // 100

    _age(db, given.id, hours=100)
    db.execute(
        update(Invoice)
        .where(Invoice.id == bill.id)
        .values(expires_at=utcnow() + timedelta(hours=1))
    )
    db.commit()
    over = _bill(db, ali["owner"])
    assert over.offer_minor == 0 and over.amount_minor == PRICE


def test_a_closed_card_or_a_paid_client_gets_no_discount(
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


def test_the_paywall_shows_the_discount_and_its_clock(
    client: TestClient, db: Session
) -> None:
    _given, ali = _offered(client, db, "wall@shop.test")
    owner = db.get(User, ali["owner"])
    assert owner is not None
    _plan(db)
    db.commit()
    shown = client.get(
        "/api/v1/billing/paywall", params={"plan": "standart"}, headers=_auth(owner)
    ).json()
    offer = shown["sales_offer"]
    assert offer["percent"] == 20 and offer["source"] == "contact"
    assert offer["next_percent"] == 10
    started = datetime.fromisoformat(offer["started_at"])
    assert datetime.fromisoformat(offer["ends_at"]) - started == timedelta(hours=24)
    assert datetime.fromisoformat(offer["next_ends_at"]) - started == timedelta(
        hours=96
    )
    left = datetime.fromisoformat(offer["ends_at"]) - datetime.fromisoformat(
        offer["server_time"]
    )
    assert timedelta(hours=23, minutes=59) < left <= timedelta(hours=24)
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


START = 4_900_000  # 49 000 so'm in tiyin


def _start(db: Session, *, code: str = "start", one_time: bool = True) -> Plan:
    plan = Plan(
        code=code,
        name=code.title(),
        price=49000,
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


def _buys_start(db: Session, owner: User, *, hours_ago: float = 0) -> Invoice:
    """Start billed and paid through the billing services, so the plan runs
    and its unused days are worth what they are in production."""
    start = db.scalar(select(Plan).where(Plan.code == "start")) or _start(db)
    _plan(db)
    at = utcnow() - timedelta(hours=hours_ago)
    invoice = billing.create_invoice(db, owner=owner, plan=start, now=at)
    bill = billing.price_invoice(
        db, invoice=invoice, promo_code="", wallet=WalletChoice.KEEP, now=at
    )
    bill.status = str(InvoiceStatus.PAID)
    bill.paid_at = at
    apply_payment(db, invoice=bill, now=at)
    db.commit()
    return bill


def _card(db: Session, owner: User) -> BoardCard:
    db.expire_all()
    card = db.scalar(
        select(BoardCard).where(
            BoardCard.board == "sales", BoardCard.owner_id == owner.id
        )
    )
    assert card is not None
    return card


def test_a_start_payment_puts_the_card_in_20_and_it_is_not_a_sale(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "starter@shop.test")
    _sweep(db)
    assert _card(db, owner).column_code == "unworked"

    _buys_start(db, owner)
    _sweep(db)
    card = _card(db, owner)
    assert card.column_code == "discount_20" and card.closed_at is None
    assert card.manager_id is None
    assert _sweep(db) == (0, 0)

    # «Lid olish» gives the Start buyer before a plain sign-up.
    _client(db, "fresh@shop.test", minutes_ago=1)
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    taken = _detail(client.post(f"{URL}/sales/take", headers=ali))
    assert taken.client.email == "starter@shop.test"
    assert taken.column == "discount_20" and taken.manager is not None
    assert [a.value for a in taken.actions] == DISCOUNT_BUTTONS
    assert taken.offer is not None and taken.offer.percent == 20
    assert taken.offer.source == "start"
    assert [h.kind for h in taken.history[:2]] == ["taken", "start_bought"]
    nxt = _detail(client.post(f"{URL}/sales/take", headers=ali))
    assert nxt.client.email == "fresh@shop.test" and nxt.column == "new_lead"

    # The manager talks: a mark, no second clock, the card stays.
    press = f"{URL}/cards/{taken.id}/actions"
    talked = _detail(client.post(press, json={"action": "contacted"}, headers=ali))
    assert talked.column == "discount_20" and talked.contact_mark == "contacted"
    assert "offered" not in [h.kind for h in talked.history]


def test_a_start_card_steps_to_10_closes_and_a_full_plan_sells_it(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "steps@shop.test")
    _sweep(db)
    bill = _buys_start(db, owner)
    _sweep(db)
    card = _card(db, owner)

    def paid_ago(hours: float) -> None:
        db.execute(
            update(Invoice)
            .where(Invoice.id == bill.id)
            .values(paid_at=utcnow() - timedelta(hours=hours))
        )
        db.commit()

    paid_ago(25)
    _sweep(db)
    assert _column(db, card.id) == "discount_10"
    paid_ago(95)
    _sweep(db)
    assert _column(db, card.id) == "discount_10"
    paid_ago(97)
    _sweep(db)
    closed = _card(db, owner)
    assert closed.column_code == "closed" and closed.close_reason == "offer_ended"
    assert closed.closed_at is not None
    assert _sweep(db) == (0, 0)

    _paid(db, owner)
    _sweep(db)
    assert _column(db, card.id) == "sold"


def test_a_start_buyer_without_a_card_gets_one_and_staff_do_not(
    client: TestClient, db: Session
) -> None:
    _live(db)
    # Signed up before the board went live: no lead card was ever opened.
    old = _client(db, "old@shop.test", minutes_ago=600)
    worker = _client(db, "worker@shop.test", is_staff=True)
    late = _client(db, "late@shop.test", minutes_ago=600)
    _sweep(db)
    assert db.scalar(select(BoardCard).where(BoardCard.owner_id == old.id)) is None

    _buys_start(db, old)
    _buys_start(db, worker)
    # Paid Start long ago: the discount is over, nothing is opened.
    _buys_start(db, late, hours_ago=100)
    _sweep(db)
    assert _card(db, old).column_code == "discount_20"
    for nobody in (worker, late):
        assert (
            db.scalar(select(BoardCard).where(BoardCard.owner_id == nobody.id)) is None
        )

    # A Start bought a day ago lands straight in 10%.
    mid = _client(db, "mid@shop.test", minutes_ago=600)
    _buys_start(db, mid, hours_ago=30)
    _sweep(db)
    assert _card(db, mid).column_code == "discount_10"


def test_a_card_the_old_rule_sold_on_start_is_a_lead_again(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "resold@shop.test")
    _sweep(db)
    card = _card(db, owner)
    # What the old sweep left: Sotildi, closed, its «sold» line written.
    now = utcnow()
    card.column_code = "sold"
    card.closed_at = now
    db.add(
        BoardCardEvent(
            card_id=card.id,
            owner_id=owner.id,
            kind="sold",
            to_column="sold",
            ref="sold",
            created_at=now,
        )
    )
    db.commit()

    _buys_start(db, owner)
    _sweep(db)
    back = _card(db, owner)
    assert back.column_code == "discount_20" and back.closed_at is None

    _paid(db, owner)
    _sweep(db)
    sold = _card(db, owner)
    assert sold.column_code == "sold" and sold.closed_at is not None


def test_a_start_payment_starts_its_own_clock_after_a_talk(
    client: TestClient, db: Session
) -> None:
    given, ali = _offered(client, db, "twice@shop.test")
    owner = db.get(User, ali["owner"])
    assert owner is not None
    _age(db, given.id, hours=30)
    _sweep(db)
    assert _column(db, given.id) == "discount_10"

    _buys_start(db, owner)
    _sweep(db)
    assert _column(db, given.id) == "discount_20"
    shown = _detail(client.get(f"{URL}/cards/{given.id}", headers=ali))
    assert shown.offer is not None and shown.offer.percent == 20
    assert shown.offer.source == "start" and shown.manager is not None

    db.execute(
        update(Invoice)
        .where(Invoice.owner_id == owner.id)
        .values(paid_at=utcnow() - timedelta(hours=25))
    )
    db.commit()
    _sweep(db)
    assert _column(db, given.id) == "discount_10"


def test_the_percent_is_taken_off_what_the_start_days_leave(
    client: TestClient, db: Session
) -> None:
    _codes(db)
    _live(db)
    owner = _client(db, "upgrade@shop.test")
    _sweep(db)
    _buys_start(db, owner)
    _sweep(db)
    # A Start holder is past the tariff wall: the prices are on Tariflar.
    wall = client.get("/api/v1/billing/paywall", headers=_auth(owner)).json()
    assert wall == {"already_open": True}

    shown = client.get(
        "/api/v1/billing", params={"plan": "standart"}, headers=_auth(owner)
    ).json()
    assert shown["sales_offer"]["percent"] == 20
    assert shown["sales_offer"]["source"] == "start"
    chosen = shown["chosen"]
    # Start was paid this minute: all its 7 days are unused.
    assert chosen["price_minor"] == PRICE and chosen["credit_minor"] == START
    offer = (PRICE - START) * 20 // 100
    assert chosen["offer_minor"] == offer
    assert chosen["due_minor"] == PRICE - START - offer
    by_code = {c["code"]: c["offer"] for c in shown["cards"]}
    assert by_code["standart"]["offer_minor"] == offer
    assert by_code["standart"]["credit_minor"] == START
    assert by_code["standart"]["due_minor"] == PRICE - START - offer

    bill = _bill(db, owner.id)
    assert bill.offer_minor == offer and bill.credit_minor == START
    assert bill.amount_minor == chosen["due_minor"]

    # A code comes off what the discount leaves; the bill agrees with the wall.
    coded = client.get(
        "/api/v1/billing",
        params={"plan": "standart", "promo": "SMALL5"},
        headers=_auth(owner),
    ).json()
    promo = (PRICE - offer) * 5 // 100
    assert coded["chosen"]["offer_minor"] == offer
    assert coded["chosen"]["promo_minor"] == promo
    assert coded["chosen"]["due_minor"] == PRICE - offer - promo - START
    again = _bill(db, owner.id, promo="SMALL5")
    assert again.amount_minor == coded["chosen"]["due_minor"]


def test_fewer_start_days_left_a_smaller_credit_and_whole_soms(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _client(db, "days@shop.test")
    _sweep(db)
    # Paid 30 hours ago: 10% now, and under six of the seven days are left.
    _buys_start(db, owner, hours_ago=30)
    _sweep(db)
    chosen = client.get(
        "/api/v1/billing", params={"plan": "standart"}, headers=_auth(owner)
    ).json()["chosen"]
    credit = chosen["credit_minor"]
    assert 0 < credit < START
    offer = (PRICE - credit) * 10 // 100
    offer -= offer % 100
    assert chosen["offer_minor"] == offer and offer % 100 == 0
    assert chosen["due_minor"] == PRICE - credit - offer
    bill = _bill(db, owner.id)
    assert bill.amount_minor == chosen["due_minor"]


def test_support_kerak_on_a_start_buyer_opens_the_ticket_at_once(
    client: TestClient, db: Session
) -> None:
    from tests.pg.test_boards_support import _live as support_live
    from tests.pg.test_boards_support import _ticket

    support_live(db)
    _live(db)
    owner = _client(db, "help@shop.test")
    _sweep(db)
    _buys_start(db, owner)
    _sweep(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))
    press = f"{URL}/cards/{card.id}/actions"
    marked = client.post(
        press,
        json={"action": "needs_support", "note": "Reklama akkaunti ulanmayapti"},
        headers=ali,
    )
    assert marked.status_code == 200, marked.text
    triggers.sweep_support(db, now=utcnow())
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert [r["code"] for r in ticket.reasons] == ["from_sales"]
    assert "Reklama akkaunti ulanmayapti" in str(ticket.reasons[0]["detail"])
