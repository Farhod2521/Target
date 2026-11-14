"""The renewal board against PostgreSQL: whose term becomes a card, what
moves it on its own, the manager's buttons, who sees it, the order, the
filters and the report."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.boards import renewal
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.schemas import (
    BoardViewOut,
    CardDetailOut,
    MeOut,
    RenewalReportOut,
)
from app.worker import beat_schedule
from tests.pg.test_boards_help_idle import _own_cabinet
from tests.pg.test_boards_me import _staff

URL = "/api/v2/office"
BOARD = f"{URL}/boards/renewal"
PRICES = {"start": 49000, "standart": 490000, "pro": 1990000}


def _plan(db: Session, code: str) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        plan = Plan(
            code=code,
            name=code.title(),
            price=PRICES[code],
            currency="UZS",
            period_days=7 if code == "start" else 30,
            is_one_time=code == "start",
            max_adsets=10,
            llm_cost_limit_minor=1000,
        )
        db.add(plan)
        db.flush()
    return plan


def _bill(
    db: Session,
    owner: User,
    code: str = "standart",
    *,
    status: str = InvoiceStatus.PAID,
    paid_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> Invoice:
    plan = _plan(db, code)
    invoice = Invoice(
        owner_id=owner.id,
        number=f"TA-{uuid.uuid4().hex[:10]}",
        plan_id=plan.id,
        amount_minor=PRICES[code] * 100,
        currency="UZS",
        period_days=plan.period_days,
        expires_at=expires_at or utcnow() + timedelta(hours=1),
        status=status,
        paid_at=(paid_at or utcnow()) if status == InvoiceStatus.PAID else None,
    )
    db.add(invoice)
    db.commit()
    return invoice


def _client(
    db: Session,
    email: str,
    *,
    code: str = "standart",
    ends_in: float = 2,
    paid: bool = True,
    **fields: Any,
) -> User:
    """A client on ``code`` whose term ends in ``ends_in`` days (negative:
    ended), who paid for it thirty days before that end."""
    person = User(
        email=email,
        full_name=email.split("@")[0].title(),
        password="!",
        phone="+998901234567",
        date_joined=utcnow() - timedelta(days=60),
        **fields,
    )
    db.add(person)
    db.flush()
    ends_at = utcnow() + timedelta(days=ends_in)
    db.add(
        Subscription(
            owner_id=person.id,
            plan_id=_plan(db, code).id,
            status=SubscriptionStatus.ACTIVE,
            extra_pages=0,
            started_at=ends_at - timedelta(days=30),
            expires_at=ends_at,
            note="",
        )
    )
    db.commit()
    if paid:
        _bill(db, person, code, paid_at=ends_at - timedelta(days=30))
    return person


def _sweep(db: Session, *, at: datetime | None = None) -> int:
    return renewal.sweep(db, now=at or utcnow())


def _cards(db: Session) -> dict[str, BoardCard]:
    """Each client's latest renewal card."""
    db.expire_all()
    found: dict[str, BoardCard] = {}
    for card in db.scalars(
        select(BoardCard)
        .where(BoardCard.board == "renewal")
        .order_by(BoardCard.term_ends_at)
    ):
        found[card.owner.email] = card
    return found


def _detail(answer: Any) -> CardDetailOut:
    assert answer.status_code == 200, answer.text
    return CardDetailOut.model_validate(answer.json())


def _board(client: TestClient, headers: dict[str, str], **params: Any) -> BoardViewOut:
    answer = client.get(BOARD, params=params, headers=headers)
    assert answer.status_code == 200, answer.text
    return BoardViewOut.model_validate(answer.json())


def _emails(view: BoardViewOut, column: str) -> list[str]:
    found = next(item for item in view.columns if item.code == column)
    return [card.client.email for card in found.cards]


def _extend(db: Session, owner: User, *, days: int = 30) -> None:
    sub = db.scalar(select(Subscription).where(Subscription.owner_id == owner.id))
    assert sub is not None
    sub.expires_at = max(sub.expires_at, utcnow()) + timedelta(days=days)
    db.commit()


def test_the_sweep_is_on_the_beat() -> None:
    names = {entry["task"] for entry in beat_schedule().values()}
    assert "app.modules.boards.tasks.sweep_renewal_board_task" in names


def test_only_paying_standart_and_pro_terms_near_their_end_get_a_card(
    db: Session,
) -> None:
    _client(db, "ending@shop.test", ends_in=2)
    _client(db, "pro@shop.test", code="pro", ends_in=1)
    _client(db, "ended@shop.test", ends_in=-5)
    _client(db, "later@shop.test", ends_in=4)
    _client(db, "longgone@shop.test", ends_in=-31)
    _client(db, "start@shop.test", code="start", ends_in=1)
    _client(db, "given@shop.test", ends_in=1, paid=False)
    _client(db, "staff@shop.test", ends_in=1, is_staff=True)
    _client(db, "blocked@shop.test", ends_in=1, is_active=False)
    # Paid Start only, then the office gave Standart: not a paying Standart.
    upgraded = _client(db, "startpaid@shop.test", ends_in=1, paid=False)
    _bill(db, upgraded, "start")

    assert _sweep(db) == 3
    cards = _cards(db)
    assert sorted(cards) == ["ended@shop.test", "ending@shop.test", "pro@shop.test"]
    assert cards["ending@shop.test"].column_code == "ending"
    assert cards["ended@shop.test"].column_code == "ended"
    assert cards["pro@shop.test"].plan_code == "pro"
    assert cards["ending@shop.test"].manager_id is None

    assert _sweep(db) == 0
    assert db.scalar(select(func.count()).select_from(BoardCardEvent)) == 3


def test_new_cards_go_to_the_chosen_manager_and_follow_a_change(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    ali = _staff(db, "ali@office.test", Role.RENEWAL)
    _staff(db, "vali@office.test", Role.RENEWAL)
    _staff(db, "sales@office.test", Role.SALES)
    people = client.get(f"{BOARD}/staff", headers=boss).json()["staff"]
    ids = {person["email"]: person["id"] for person in people}
    assert sorted(ids) == ["ali@office.test", "vali@office.test"]

    assert client.get(f"{BOARD}/manager", headers=ali).status_code == 404
    assert client.get(f"{BOARD}/manager", headers=boss).json()["manager"] is None
    sales_id = str(db.scalar(select(User.id).where(User.email == "sales@office.test")))
    wrong = client.put(f"{BOARD}/manager", json={"staff_id": sales_id}, headers=boss)
    assert wrong.status_code == 422

    put = client.put(
        f"{BOARD}/manager", json={"staff_id": ids["ali@office.test"]}, headers=boss
    )
    assert put.status_code == 200 and put.json()["moved"] == 0
    _client(db, "one@shop.test")
    done = _client(db, "done@shop.test")
    _sweep(db)
    _bill(db, done)
    _sweep(db)
    cards = _cards(db)
    assert cards["one@shop.test"].manager.email == "ali@office.test"
    assert cards["done@shop.test"].column_code == "renewed"

    put = client.put(
        f"{BOARD}/manager", json={"staff_id": ids["vali@office.test"]}, headers=boss
    )
    assert put.json()["moved"] == 1
    assert put.json()["manager"]["email"] == "vali@office.test"
    cards = _cards(db)
    assert cards["one@shop.test"].manager.email == "vali@office.test"
    # A finished card keeps who worked it.
    assert cards["done@shop.test"].manager.email == "ali@office.test"

    _client(db, "two@shop.test")
    _sweep(db)
    assert _cards(db)["two@shop.test"].manager.email == "vali@office.test"


def test_who_sees_the_board(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    ali = _staff(db, "ali@office.test", Role.RENEWAL)
    vali = _staff(db, "vali@office.test", Role.RENEWAL)
    lead = _staff(db, "lead@office.test", Role.SALES_LEAD)
    sales = _staff(db, "sales@office.test", Role.SALES)
    support = _staff(db, "support@office.test", Role.SUPPORT)
    owner = _staff(db, "owner@office.test", Role.OWNER)
    ali_id = str(db.scalar(select(User.id).where(User.email == "ali@office.test")))
    client.put(f"{BOARD}/manager", json={"staff_id": ali_id}, headers=boss)
    _client(db, "one@shop.test")
    _sweep(db)

    me = MeOut.model_validate(client.get(f"{URL}/me", headers=ali).json())
    assert [(b.code, b.lead) for b in me.boards] == [("renewal", False)]
    assert me.default_board == "renewal"
    assert not me.can.take and not me.can.add_lead and not me.can.add_ticket
    assert not me.can.client_card and not me.can.renewal_manager
    assert client.get(f"{URL}/boards/sales", headers=ali).status_code == 404
    assert client.get(f"{URL}/boards/support", headers=ali).status_code == 404

    lead_me = MeOut.model_validate(client.get(f"{URL}/me", headers=lead).json())
    assert ("renewal", True) in [(b.code, b.lead) for b in lead_me.boards]
    owner_me = MeOut.model_validate(client.get(f"{URL}/me", headers=owner).json())
    assert owner_me.can.client_card and owner_me.can.renewal_manager

    for nobody in (sales, support):
        assert client.get(BOARD, headers=nobody).status_code == 404
        assert client.get(f"{BOARD}/reasons", headers=nobody).status_code == 404
        assert client.get(f"{BOARD}/report", headers=nobody).status_code == 404

    assert _emails(_board(client, ali), "ending") == ["one@shop.test"]
    assert _emails(_board(client, vali), "ending") == []
    for whole in (lead, owner, boss):
        assert _emails(_board(client, whole), "ending") == ["one@shop.test"]

    card_id = _cards(db)["one@shop.test"].id
    assert client.get(f"{URL}/cards/{card_id}", headers=vali).status_code == 404
    assert client.get(f"{URL}/cards/{card_id}", headers=sales).status_code == 404
    # Nobody opens a renewal card by hand.
    add = client.post(
        f"{BOARD}/cards", json={"user_id": str(uuid.uuid4())}, headers=boss
    )
    assert add.status_code == 404


def test_the_buttons_follow_the_column(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    _client(db, "one@shop.test")
    _sweep(db)
    card = _detail(
        client.get(f"{URL}/cards/{_cards(db)['one@shop.test'].id}", headers=boss)
    )
    press = f"{URL}/cards/{card.id}/actions"
    assert [a.value for a in card.actions] == [
        "contacted",
        "no_contact",
        "callback",
        "decline",
    ]
    assert card.renewal is not None and card.renewal.plan_code == "standart"
    assert card.renewal.days == 2 and not card.renewal.ended

    assert (
        client.post(press, json={"action": "will_pay"}, headers=boss).status_code == 409
    )
    for _ in range(2):
        card = _detail(client.post(press, json={"action": "no_contact"}, headers=boss))
    assert card.column == "no_contact" and card.attempts == 2

    no_time = client.post(press, json={"action": "callback"}, headers=boss)
    assert no_time.status_code == 422
    due = (utcnow() + timedelta(hours=3)).isoformat()
    card = _detail(
        client.post(press, json={"action": "callback", "due_at": due}, headers=boss)
    )
    assert card.column == "callback" and card.due_at is not None

    card = _detail(client.post(press, json={"action": "contacted"}, headers=boss))
    assert card.column == "contacted" and card.due_at is None
    assert [a.value for a in card.actions] == ["callback", "will_pay", "decline"]
    card = _detail(client.post(press, json={"action": "will_pay"}, headers=boss))
    assert card.column == "awaiting"

    no_reason = client.post(press, json={"action": "decline"}, headers=boss)
    assert no_reason.status_code == 422
    sales_reason = client.post(
        press, json={"action": "decline", "reason": "wrong_number"}, headers=boss
    )
    assert sales_reason.status_code == 422
    wordless = client.post(
        press, json={"action": "decline", "reason": "other"}, headers=boss
    )
    assert wordless.status_code == 422
    card = _detail(
        client.post(
            press,
            json={"action": "decline", "reason": "expensive", "note": "490 ming ko'p"},
            headers=boss,
        )
    )
    assert card.column == "declined" and card.closed_at is not None
    assert card.close_reason == "expensive" and card.close_reason_label == "Qimmat"
    assert card.actions == []
    assert card.history[0].kind == "declined"
    assert card.history[0].body == "Qimmat. 490 ming ko'p"
    again = client.post(press, json={"action": "contacted"}, headers=boss)
    assert again.status_code == 409

    reasons = client.get(f"{BOARD}/reasons", headers=boss).json()
    assert [r["value"] for r in reasons] == [
        "expensive",
        "no_result",
        "meta_problem",
        "business_stopped",
        "switched",
        "no_answer",
        "other",
    ]


def test_the_term_ending_moves_only_a_card_still_in_tugayapti(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    _client(db, "quiet@shop.test", ends_in=1)
    _client(db, "talked@shop.test", ends_in=1)
    _sweep(db)
    talked = _cards(db)["talked@shop.test"].id
    client.post(
        f"{URL}/cards/{talked}/actions", json={"action": "contacted"}, headers=boss
    )

    later = utcnow() + timedelta(days=1, minutes=5)
    _sweep(db, at=later)
    cards = _cards(db)
    assert cards["quiet@shop.test"].column_code == "ended"
    assert cards["talked@shop.test"].column_code == "contacted"


def test_a_payment_renews_from_any_column_and_the_next_term_is_a_new_card(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    one = _client(db, "one@shop.test")
    gone = _client(db, "gone@shop.test", ends_in=-3)
    _sweep(db)
    gone_card = _cards(db)["gone@shop.test"].id
    client.post(
        f"{URL}/cards/{gone_card}/actions",
        json={"action": "decline", "reason": "no_result"},
        headers=boss,
    )

    bill = _bill(db, one)
    _extend(db, one)
    _bill(db, gone, "pro")
    assert _sweep(db) == 2
    cards = _cards(db)
    assert cards["one@shop.test"].column_code == "renewed"
    assert cards["one@shop.test"].invoice_id == bill.id
    assert cards["one@shop.test"].closed_at is not None
    assert cards["gone@shop.test"].column_code == "renewed"
    assert cards["gone@shop.test"].close_reason == ""
    detail = _detail(client.get(f"{URL}/cards/{gone_card}", headers=boss))
    assert detail.renewal is not None and detail.renewal.paid is not None
    assert detail.renewal.paid.minor == PRICES["pro"] * 100
    assert detail.renewal.payments == 2
    assert _sweep(db) == 0

    # The renewed term runs out in its turn: a card of its own.
    near = utcnow() + timedelta(days=30)
    assert _sweep(db, at=near) == 1
    db.expire_all()
    mine = list(
        db.scalars(
            select(BoardCard)
            .where(BoardCard.board == "renewal", BoardCard.owner_id == one.id)
            .order_by(BoardCard.term_ends_at)
        )
    )
    assert [card.column_code for card in mine] == ["renewed", "ending"]
    # The old payment does not renew the new term.
    assert _sweep(db, at=near + timedelta(minutes=1)) == 0
    assert _cards(db)["one@shop.test"].column_code == "ending"


def test_a_bill_moves_the_card_and_an_unpaid_one_brings_it_back(
    db: Session,
) -> None:
    one = _client(db, "one@shop.test")
    start = _client(db, "startbill@shop.test")
    _sweep(db)
    _bill(
        db,
        one,
        status=InvoiceStatus.PENDING,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    # A Start bill is not a renewal.
    _bill(db, start, "start", status=InvoiceStatus.PENDING)
    _sweep(db)
    cards = _cards(db)
    assert cards["one@shop.test"].column_code == "awaiting"
    assert cards["startbill@shop.test"].column_code == "ending"

    _sweep(db, at=utcnow() + timedelta(minutes=31))
    card = _cards(db)["one@shop.test"]
    assert card.column_code == "callback" and card.due_at is not None
    kinds = list(
        db.scalars(
            select(BoardCardEvent.kind)
            .where(BoardCardEvent.card_id == card.id)
            .order_by(BoardCardEvent.created_at)
        )
    )
    assert kinds == ["term_ending", "bill_opened", "bill_unpaid"]


def test_thirty_days_of_silence_decline_the_card(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    _client(db, "silent@shop.test", ends_in=-1)
    _client(db, "noanswer@shop.test", ends_in=-1)
    _client(db, "talked@shop.test", ends_in=-1)
    _sweep(db)
    cards = _cards(db)
    client.post(
        f"{URL}/cards/{cards['noanswer@shop.test'].id}/actions",
        json={"action": "no_contact"},
        headers=boss,
    )
    client.post(
        f"{URL}/cards/{cards['talked@shop.test'].id}/actions",
        json={"action": "contacted"},
        headers=boss,
    )

    _sweep(db, at=utcnow() + timedelta(days=28))
    assert _cards(db)["silent@shop.test"].column_code == "ended"
    _sweep(db, at=utcnow() + timedelta(days=30))
    cards = _cards(db)
    assert cards["silent@shop.test"].column_code == "declined"
    assert cards["silent@shop.test"].close_reason == "no_answer"
    assert cards["noanswer@shop.test"].column_code == "declined"
    assert cards["talked@shop.test"].column_code == "contacted"


def test_days_the_office_gives_move_the_term_not_the_card(db: Session) -> None:
    one = _client(db, "one@shop.test", ends_in=-2)
    _sweep(db)
    assert _cards(db)["one@shop.test"].column_code == "ended"

    _extend(db, one, days=10)
    assert _sweep(db) == 1
    db.expire_all()
    cards = list(db.scalars(select(BoardCard).where(BoardCard.owner_id == one.id)))
    assert len(cards) == 1
    assert cards[0].column_code == "ending" and cards[0].closed_at is None
    sub = db.scalar(select(Subscription).where(Subscription.owner_id == one.id))
    assert sub is not None and cards[0].term_ends_at == sub.expires_at
    assert _sweep(db) == 0


def test_the_order_the_filters_and_the_search(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    _client(db, "two@shop.test", ends_in=2.5)
    _client(db, "soon@shop.test", ends_in=0.5)
    _client(db, "pro@shop.test", code="pro", ends_in=1.5)
    _client(db, "old@shop.test", ends_in=-9)
    fresh = _client(db, "fresh@shop.test", ends_in=-1)
    _account, page = _own_cabinet(db, fresh)
    page.name = "Gulzor Mebel"
    page.is_active = True
    db.commit()
    _sweep(db)

    view = _board(client, boss)
    assert [column.code for column in view.columns] == [
        "ending",
        "ended",
        "no_contact",
        "contacted",
        "callback",
        "awaiting",
        "renewed",
        "declined",
    ]
    assert view.take is None
    assert _emails(view, "ending") == [
        "soon@shop.test",
        "pro@shop.test",
        "two@shop.test",
    ]
    assert _emails(view, "ended") == ["fresh@shop.test", "old@shop.test"]

    assert _emails(_board(client, boss, plan="pro"), "ending") == ["pro@shop.test"]
    assert _emails(_board(client, boss, plan="start"), "ending") == []
    assert _emails(_board(client, boss, q="gulzor"), "ended") == ["fresh@shop.test"]
    assert _emails(_board(client, boss, q="gulzor"), "ending") == []
    today = localtime(utcnow()).date()
    ranged = _board(
        client,
        boss,
        term_from=(today - timedelta(days=3)).isoformat(),
        term_to=today.isoformat(),
    )
    assert "old@shop.test" not in _emails(ranged, "ended")
    assert "fresh@shop.test" in _emails(ranged, "ended")
    assert "two@shop.test" not in _emails(ranged, "ending")

    cards = _cards(db)
    press = f"{URL}/cards/{cards['old@shop.test'].id}/actions"
    for _ in range(3):
        client.post(press, json={"action": "no_contact"}, headers=boss)
    assert _emails(_board(client, boss, attempts="3+"), "no_contact") == [
        "old@shop.test"
    ]
    assert _emails(_board(client, boss, attempts="0"), "no_contact") == []
    client.post(press, json={"action": "decline", "reason": "switched"}, headers=boss)
    assert _emails(_board(client, boss, reason="switched"), "declined") == [
        "old@shop.test"
    ]
    assert _emails(_board(client, boss, reason="expensive"), "declined") == []

    # Qayta aloqa: the late one on top, by the set time.
    for email, hours in (("two@shop.test", 5), ("pro@shop.test", 1)):
        client.post(
            f"{URL}/cards/{cards[email].id}/actions",
            json={
                "action": "callback",
                "due_at": (utcnow() + timedelta(hours=hours)).isoformat(),
            },
            headers=boss,
        )
    assert _emails(_board(client, boss), "callback") == [
        "pro@shop.test",
        "two@shop.test",
    ]
    card = _detail(
        client.get(f"{URL}/cards/{cards['fresh@shop.test'].id}", headers=boss)
    )
    assert card.renewal is not None and card.renewal.pages == ["Gulzor Mebel"]
    assert card.renewal.ended and card.renewal.days == -1


def test_the_report_counts_the_period_by_plan(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    ali = _staff(db, "ali@office.test", Role.RENEWAL)
    renewed = _client(db, "renewed@shop.test", ends_in=1)
    _client(db, "declined@shop.test", ends_in=-2)
    _client(db, "open@shop.test", ends_in=2)
    pro = _client(db, "pro@shop.test", code="pro", ends_in=1)
    _sweep(db)
    _bill(db, renewed)
    _bill(db, pro, "pro")
    client.post(
        f"{URL}/cards/{_cards(db)['declined@shop.test'].id}/actions",
        json={"action": "decline", "reason": "expensive"},
        headers=boss,
    )
    _sweep(db)

    today = localtime(utcnow()).date()
    answer = client.get(
        f"{BOARD}/report",
        params={
            "date_from": (today - timedelta(days=5)).isoformat(),
            "date_to": (today + timedelta(days=5)).isoformat(),
        },
        headers=boss,
    )
    assert answer.status_code == 200, answer.text
    report = RenewalReportOut.model_validate(answer.json())
    standart, pro_line = report.plans
    assert (standart.code, standart.due, standart.renewed) == ("standart", 3, 1)
    assert (standart.declined, standart.open, standart.rate) == (1, 1, 33)
    assert standart.paid[0].minor == PRICES["standart"] * 100
    assert [(r.code, r.count) for r in standart.reasons] == [("expensive", 1)]
    assert (pro_line.due, pro_line.renewed, pro_line.rate) == (1, 1, 100)
    assert (report.total.due, report.total.renewed, report.total.rate) == (4, 2, 50)
    assert report.total.paid[0].minor == (PRICES["standart"] + PRICES["pro"]) * 100

    # A manager's report counts their own cards: none here.
    mine = RenewalReportOut.model_validate(
        client.get(f"{BOARD}/report", headers=ali).json()
    )
    assert mine.total.due == 0
    bad = client.get(
        f"{BOARD}/report",
        params={"date_from": "2026-05-01", "date_to": "2026-04-01"},
        headers=boss,
    )
    assert bad.status_code == 422


def test_the_lead_gives_a_card_to_a_renewal_manager_only(
    client: TestClient, db: Session
) -> None:
    lead = _staff(db, "lead@office.test", Role.SALES_LEAD)
    ali = _staff(db, "ali@office.test", Role.RENEWAL)
    _staff(db, "sales@office.test", Role.SALES)
    _client(db, "one@shop.test")
    _sweep(db)
    card_id = _cards(db)["one@shop.test"].id
    ids = {
        email: str(db.scalar(select(User.id).where(User.email == email)))
        for email in ("ali@office.test", "sales@office.test")
    }
    give = f"{URL}/cards/{card_id}/assign"
    wrong = client.post(give, json={"staff_id": ids["sales@office.test"]}, headers=lead)
    assert wrong.status_code == 422
    card = _detail(
        client.post(give, json={"staff_id": ids["ali@office.test"]}, headers=lead)
    )
    assert card.column == "ending" and card.manager is not None
    assert card.history[0].kind == "assigned"
    assert client.post(give, json={"staff_id": None}, headers=ali).status_code == 404
    back = _detail(client.post(give, json={"staff_id": None}, headers=lead))
    assert back.column == "ending" and back.manager is None
