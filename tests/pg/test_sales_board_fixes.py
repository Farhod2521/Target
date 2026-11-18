"""The Sales board's 2026-11-19 additions against PostgreSQL: the report,
«Lid olish»'s limit and order, the attempts filter, where a lead came from,
the Telegram notices, the dashboard's figures, and the phone: who is
calling with their plan, and a staff member who takes no calls."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Subscription
from app.modules.boards import notices
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.schemas import BoardViewOut, SalesReportOut
from app.modules.telephony.models import PhoneExtension
from tests.conftest import SIGNUP
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client, _detail, _live, _paid, _plan, _sweep
from tests.pg.test_telephony_calls import _card, office  # noqa: F401
from tests.pg.test_telephony_live import _moment
from tests.pg.test_telephony_settings import exchange  # noqa: F401

URL = "/api/v2/office"


def _report(client: TestClient, head: dict[str, str], **params: Any) -> SalesReportOut:
    answer = client.get(f"{URL}/boards/sales/report", params=params, headers=head)
    assert answer.status_code == 200, answer.text
    return SalesReportOut.model_validate(answer.json())


def _person(db: Session, email: str) -> User:
    found = db.scalar(select(User).where(User.email == email))
    assert found is not None
    return found


def test_the_report_counts_each_day_and_each_person(
    client: TestClient, db: Session
) -> None:
    _live(db)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)
    ali = _staff(db, "ali@office.test", Role.SALES)
    vali = _staff(db, "vali@office.test", Role.SALES)
    for name in ("one", "two", "three", "four"):
        _client(db, f"{name}@shop.test")
    _sweep(db)

    first = _detail(client.post(f"{URL}/sales/take", headers=ali))
    client.post(
        f"{URL}/cards/{first.id}/actions", json={"action": "contacted"}, headers=ali
    )
    second = _detail(client.post(f"{URL}/sales/take", headers=ali))
    client.post(
        f"{URL}/cards/{second.id}/actions",
        json={"action": "close", "reason": "expensive"},
        headers=ali,
    )
    third = _detail(client.post(f"{URL}/sales/take", headers=vali))
    client.post(
        f"{URL}/cards/{third.id}/actions", json={"action": "no_contact"}, headers=vali
    )
    # Ali's first client pays Standart: his sale, with the bill's money.
    _paid(db, _person(db, first.client.email))
    _sweep(db)

    whole = _report(client, lead)
    assert whole.scope == "all"
    assert whole.total.leads == 4
    assert whole.total.taken == 3
    assert whole.total.contacted == 1 and whole.total.no_contact == 1
    assert whole.total.sold == 1 and whole.total.closed == 1
    assert whole.total.rate == 25
    assert whole.total.money[0].minor == 49000000
    assert whole.total.first_touch_minutes == 0
    assert len(whole.days) == 30 and whole.days[-1].leads == 4
    assert [r.code for r in whole.reasons] == ["expensive"]
    assert whole.queue is not None and whole.queue.waiting == 1
    rows = {row.staff.email: row for row in whole.staff if row.staff}
    assert rows["ali@office.test"].sold == 1
    assert rows["ali@office.test"].taken == 2
    assert rows["ali@office.test"].rate == 50
    assert rows["vali@office.test"].no_contact == 1
    assert rows["vali@office.test"].open_now == 1
    # Every Sales person has a row, idle or not: the lead counts too.
    assert "rahbar@office.test" in rows

    # A manager reads their own figures only.
    own = _report(client, vali)
    assert own.scope == "own"
    assert [row.staff.email for row in own.staff if row.staff] == ["vali@office.test"]
    assert own.total.taken == 1 and own.total.sold == 0 and own.total.leads == 0
    assert own.queue is None and own.sources == []

    # A period before anything happened is all zeros, a day per day.
    old = _report(client, lead, date_from="2026-01-01", date_to="2026-01-03")
    assert old.total.taken == 0 and [d.day.day for d in old.days] == [1, 2, 3]
    assert (
        client.get(
            f"{URL}/boards/sales/report",
            params={"date_from": "2026-01-03", "date_to": "2026-01-01"},
            headers=lead,
        ).status_code
        == 422
    )
    support = _staff(db, "yordam@office.test", Role.SUPPORT)
    assert client.get(f"{URL}/boards/sales/report", headers=support).status_code == 404


def test_lid_olish_stops_at_five_uncalled_and_gives_the_warmest_first(
    client: TestClient, db: Session
) -> None:
    _live(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    for n in range(7):
        _client(db, f"c{n}@shop.test", minutes_ago=10 - n)
    # The oldest sign-up opened a bill: it goes first though newest go first.
    warm = _person(db, "c0@shop.test")
    _paid(db, warm, status=InvoiceStatus.PENDING)
    db.execute(
        update(Invoice)
        .where(Invoice.owner_id == warm.id)
        .values(expires_at=utcnow() + timedelta(hours=1))
    )
    db.commit()
    _sweep(db)

    board = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/sales", headers=ali).json()
    )
    assert board.take is not None and board.take.limit == 5
    assert board.take.queue == 7 and board.take.working == 0
    # Ishlanmagan is the lead's column.
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)
    board = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/sales", headers=lead).json()
    )
    unworked = next(c for c in board.columns if c.code == "unworked")
    hot = next(card for card in unworked.cards if card.client.email == "c0@shop.test")
    assert hot.heat is not None and hot.heat.level == "hot" and hot.heat.bill

    taken = [_detail(client.post(f"{URL}/sales/take", headers=ali)) for _ in range(5)]
    assert taken[0].client.email == "c0@shop.test"
    assert taken[1].client.email == "c6@shop.test"
    refused = client.post(f"{URL}/sales/take", headers=ali)
    assert refused.status_code == 409 and refused.json()["code"] == "lead_take_limit"
    # One called: room for one more.
    client.post(
        f"{URL}/cards/{taken[1].id}/actions",
        json={"action": "no_contact"},
        headers=ali,
    )
    _detail(client.post(f"{URL}/sales/take", headers=ali))
    view = client.get(f"{URL}/boards/sales", headers=ali).json()
    assert view["take"]["working"] == 5

    # «Bog'lanilmadi» filter on Sotuv too.
    tried = client.get(f"{URL}/boards/sales", params={"attempts": "1-2"}, headers=ali)
    shown = [card for col in tried.json()["columns"] for card in col["cards"]]
    assert [card["client"]["email"] for card in shown] == ["c6@shop.test"]


def test_a_sign_up_keeps_how_and_from_where_it_came(
    client: TestClient, db: Session
) -> None:
    _live(db)
    answer = client.post(
        "/api/v1/auth/signup",
        json=SIGNUP
        | {
            "email": "utm@example.com",
            "utm": {"source": "instagram", "campaign": "noyabr", "junk": "x" * 500},
        },
    )
    assert answer.status_code == 201, answer.text
    person = _person(db, "utm@example.com")
    assert person.signup_via == "email"
    assert person.signup_utm == {"source": "instagram", "campaign": "noyabr"}
    _sweep(db)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)
    card = db.scalar(select(BoardCard).where(BoardCard.owner_id == person.id))
    assert card is not None
    detail = _detail(client.get(f"{URL}/cards/{card.id}", headers=lead))
    assert detail.client.signup_via_label == "Email bilan"
    assert detail.client.utm == {"source": "instagram", "campaign": "noyabr"}
    report = _report(client, lead)
    assert [(s.code, s.leads) for s in report.sources] == [("email", 1)]
    assert [(c.source, c.campaign, c.leads) for c in report.campaigns] == [
        ("instagram", "noyabr", 1)
    ]


class _Bot:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, *, chat_id: str, text: str, **_: Any) -> None:
        self.sent.append((chat_id, text))


def _chat(db: Session, email: str, chat_id: str) -> None:
    from app.modules.notifications.models import StaffChat

    db.add(
        StaffChat(
            owner_id=_person(db, email).id,
            chat_id=chat_id,
            is_active=True,
            linked_at=utcnow(),
        )
    )
    db.commit()


def test_telegram_tells_a_due_time_a_bill_and_new_leads_once(
    client: TestClient, db: Session
) -> None:
    _live(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    _chat(db, "ali@office.test", "500")
    _client(db, "shop@shop.test")
    _sweep(db)
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))
    now = utcnow()
    db.execute(
        update(BoardCard)
        .where(BoardCard.id == card.id)
        .values(due_at=now - timedelta(minutes=2))
    )
    db.commit()
    bot = _Bot()

    assert notices.remind_due(db, client=bot, now=now) == 1  # type: ignore[arg-type]
    assert notices.remind_due(db, client=bot, now=now) == 0  # type: ignore[arg-type]
    assert bot.sent[0][0] == "500" and "Shop" in bot.sent[0][1]

    _paid(db, _person(db, "shop@shop.test"), status=InvoiceStatus.PENDING)
    db.execute(update(Invoice).values(expires_at=now + timedelta(hours=1)))
    db.commit()
    assert notices.tell_bills(db, client=bot, now=now) == 1  # type: ignore[arg-type]
    assert notices.tell_bills(db, client=bot, now=now) == 0  # type: ignore[arg-type]
    kinds = set(
        db.scalars(select(BoardCardEvent.kind).where(BoardCardEvent.card_id == card.id))
    )
    assert {"due_reminded", "bill_told"} <= kinds

    # The queue: told in working hours, once for the same leads.
    from app.common.cache import cache

    cache.delete(notices.QUEUE_TOLD_KEY)
    _client(db, "late@shop.test")
    _sweep(db)
    noon = now.replace(hour=7, minute=0)  # 12:00 in Tashkent
    assert notices.tell_queue(db, client=bot, now=noon) == 1  # type: ignore[arg-type]
    assert notices.tell_queue(db, client=bot, now=noon) == 0  # type: ignore[arg-type]
    night = now.replace(hour=20)  # 01:00 in Tashkent
    cache.delete(notices.QUEUE_TOLD_KEY)
    assert notices.tell_queue(db, client=bot, now=night) == 0  # type: ignore[arg-type]


def test_the_dashboard_counts_the_board_s_sales(client: TestClient, db: Session) -> None:
    from app.modules.backoffice.selectors.dashboard import Window, sales

    _live(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    _client(db, "shop@shop.test")
    _client(db, "other@shop.test")
    _sweep(db)
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))
    _detail(client.post(f"{URL}/sales/take", headers=ali))
    _paid(db, _person(db, card.client.email))
    _sweep(db)
    today = utcnow().date()
    window = Window(
        period="custom",
        unit="day",
        start=today - timedelta(days=1),
        end=today + timedelta(days=1),
    )
    rows = sales(db, window=window)
    assert [(row.manager.email, row.sold, row.open) for row in rows] == [
        ("ali@office.test", 1, 1)
    ]


def test_a_call_shows_the_plan_and_a_person_who_takes_none_is_skipped(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    owner = _client(db, "shop@shop.test")
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=_plan(db).id,
            status=SubscriptionStatus.ACTIVE,
            extra_pages=0,
            started_at=utcnow(),
            expires_at=utcnow() + timedelta(days=12, hours=3),
            note="",
        )
    )
    db.commit()
    _paid(db, owner)
    card = _card(db, owner, "sales", "new_lead")
    card.manager_id = office["people"]["sotuv@office.test"].id
    db.commit()
    renewal = _card(db, owner, "renewal", "ending")
    assert renewal.id

    client.post(office["hook"], json=_moment("call_started", "c1", src="901234567"))
    live = client.get(f"{URL}/telephony/live", headers=office["boss"]).json()
    shown = live["calls"][0]["clients"][0]
    assert shown["standing"]["label"] == "«Standart» · 13 kun qoldi"
    assert shown["standing"]["paid"] is True
    assert shown["renewal_card_id"] == str(renewal.id)
    route = client.get(f"{office['hook']}/route", params={"number": "901234567"})
    assert route.json()["extension"] == "101"
    assert route.json()["contact_name"] == "Shop · «Standart» · 13 kun qoldi"

    # The seller takes no calls now: nobody is put through, calls out still work.
    off = client.put(
        f"{URL}/telephony/me/accepting",
        json={"accepts_calls": False},
        headers=office["seller"],
    )
    assert off.status_code == 200 and off.json()["accepts_calls"] is False
    assert client.get(f"{URL}/telephony/me", headers=office["seller"]).json()[
        "accepts_calls"
    ] is False
    route = client.get(f"{office['hook']}/route", params={"number": "901234567"})
    assert route.json()["extension"] is None
    colleagues = client.get(
        f"{URL}/telephony/colleagues", headers=office["helper"]
    ).json()["colleagues"]
    assert [(c["number"], c["accepts_calls"]) for c in colleagues] == [("101", False)]
    seat = db.scalar(select(PhoneExtension).where(PhoneExtension.number == "101"))
    assert seat is not None and seat.accepts_calls is False

    lead = _staff(db, "nophone@office.test", Role.SALES)
    refused = client.put(
        f"{URL}/telephony/me/accepting", json={"accepts_calls": False}, headers=lead
    )
    assert refused.status_code == 409
