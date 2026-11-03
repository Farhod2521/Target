"""The payments group's bot: a receipt for each paid bill and nothing else, and
the day's, week's and month's totals by plan once each has ended."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import ChatUnreachable

from app.common.cache import cache
from app.common.config import settings
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import (
    InvoiceKind,
    InvoiceStatus,
    ManualMethod,
    TransactionState,
)
from app.modules.billing.models import Invoice, PaymentTransaction, Plan
from app.modules.billing.services import record_payment
from app.modules.notifications.services import payments_desk
from app.modules.notifications.services.payments_desk import (
    send_receipts,
    send_reports,
)
from tests.pg.test_office_actions import _shop, _staff
from tests.pg.test_office_telegram import FakeBot

GROUP = "-1001234567890"
# Monday 2 November 2026, 00:05 in Tashkent (UTC+5): a day and a week ended.
MONDAY_NIGHT = datetime(2026, 11, 1, 19, 5, tzinfo=UTC)
# Sunday 1 November 2026, 00:05 in Tashkent: a day and October ended.
FIRST_NIGHT = datetime(2026, 10, 31, 19, 5, tzinfo=UTC)


class BrokenBot(FakeBot):
    def send_message(self, **fields: object):  # type: ignore[no-untyped-def,override]
        self.calls.append(("send_message", dict(fields)))
        raise ChatUnreachable("chat not found", code=400)


@pytest.fixture
def group(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    client = FakeBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield client

    monkeypatch.setattr(payments_desk, "payments_bot", opened)
    monkeypatch.setattr(settings, "payments_bot_token", "t")
    monkeypatch.setattr(settings, "payments_bot_username", "pay_bot")
    monkeypatch.setattr(settings, "payments_bot_chat_id", GROUP)
    monkeypatch.setattr(settings, "payments_bot_thread_id", 7)
    monkeypatch.setattr(settings, "site_url", "https://targetolog.test")
    for kind, start in (
        ("day", "2026-11-01"),
        ("week", "2026-10-26"),
        ("day", "2026-10-31"),
        ("month", "2026-10-01"),
    ):
        cache.delete(f"notifications:payments-report:{kind}:{start}")
    return client


def _bill(
    db: Session,
    plan: Plan,
    owner: User | None,
    number: str,
    *,
    status: str = InvoiceStatus.PAID,
    paid_at: datetime | None = None,
    **fields: object,
) -> Invoice:
    now = utcnow()
    bill = Invoice(
        owner_id=owner.id if owner else None,
        number=number,
        plan_id=plan.id,
        amount_minor=fields.pop("amount_minor", 49_000_000),
        currency="UZS",
        period_days=30,
        expires_at=now + timedelta(days=1),
        status=status,
        paid_at=(paid_at or now) if status in ("paid", "refunded") else None,
        **fields,
    )
    db.add(bill)
    db.flush()
    return bill


def _customer(db: Session, email: str, name: str) -> User:
    user = User(email=email, full_name=name, password="!", phone="+998901112233")
    db.add(user)
    db.flush()
    return user


def _plan(db: Session, code: str, name: str, order: int) -> Plan:
    plan = Plan(
        code=code,
        name=name,
        price=990000,
        currency="UZS",
        period_days=30,
        max_adsets=10,
        llm_cost_limit_minor=1000,
        sort_order=order,
    )
    db.add(plan)
    db.flush()
    return plan


def test_only_a_paid_bill_that_took_money_gets_a_receipt(
    db: Session, group: FakeBot
) -> None:
    customer, plan = _shop(db)
    paid = _bill(db, plan, customer, "1001")
    db.add(
        PaymentTransaction(
            owner_id=customer.id,
            invoice_id=paid.id,
            provider="payme",
            external_id="ext-1001",
            reference="ref-1001",
            state=TransactionState.PERFORMED,
            amount_minor=paid.amount_minor,
            currency="UZS",
            performed_at=utcnow(),
        )
    )
    for number, status in (
        ("1002", InvoiceStatus.PENDING),
        ("1003", InvoiceStatus.HELD),
        ("1004", InvoiceStatus.CANCELED),
        ("1005", InvoiceStatus.EXPIRED),
        ("1006", InvoiceStatus.REFUNDED),
    ):
        _bill(db, plan, customer, number, status=status)
    _bill(db, plan, customer, "1007", amount_minor=0, wallet_minor=49_000_000)
    _bill(db, plan, customer, "1008", archived_at=utcnow())
    _bill(db, plan, customer, "1009", paid_at=utcnow() - timedelta(days=3))
    db.commit()

    assert send_receipts(db, now=utcnow()) == 1
    assert send_receipts(db, now=utcnow()) == 0

    [text] = [t.replace("\xa0", " ") for t in group.texts()]
    assert group.calls[0][1]["chat_id"] == GROUP
    assert group.calls[0][1]["thread_id"] == 7
    assert "To'lov qabul qilindi" in text
    assert "490 000" in text
    assert "Pro tarifi · 30 kun" in text
    assert "Payme" in text
    assert "<code>1001</code>" in text
    assert "shop@client.test" in text
    assert f"/ofis/mijozlar/{customer.id}/" in text
    db.expire_all()
    owed = db.scalars(
        select(Invoice.number).where(Invoice.receipt_sent_at.is_not(None))
    ).all()
    assert owed == ["1001"]


def test_a_payment_written_in_the_office_goes_with_its_method(
    db: Session, group: FakeBot
) -> None:
    customer, plan = _shop(db)
    actor, _ = _staff(db, Role.FINANCE, email="cash@office.test")
    record_payment(
        db,
        owner=customer,
        plan=plan,
        amount_minor=30_000_000,
        days=30,
        method=ManualMethod.CASH,
        reference="",
        actor=actor,
        reason="kassaga naqd",
        now=utcnow(),
    )
    db.commit()

    assert send_receipts(db, now=utcnow()) == 1
    [text] = [t.replace("\xa0", " ") for t in group.texts()]
    assert "Naqd (ofisda yozildi)" in text
    assert "300 000" in text


def test_a_refused_post_is_tried_again_and_stops_the_run(
    db: Session, monkeypatch: pytest.MonkeyPatch, group: FakeBot
) -> None:
    customer, plan = _shop(db)
    _bill(db, plan, customer, "2001")
    _bill(db, plan, customer, "2002")
    db.commit()
    broken = BrokenBot()

    @contextmanager
    def opened() -> Iterator[FakeBot]:
        yield broken

    monkeypatch.setattr(payments_desk, "payments_bot", opened)

    assert send_receipts(db, now=utcnow()) == 0
    assert len(broken.texts()) == 1
    db.expire_all()
    assert (
        db.scalars(select(Invoice).where(Invoice.receipt_sent_at.is_not(None))).all()
        == []
    )

    monkeypatch.setattr(payments_desk, "payments_bot", lambda: _yield(group))
    assert send_receipts(db, now=utcnow()) == 2


@contextmanager
def _yield(client: FakeBot) -> Iterator[FakeBot]:
    yield client


def test_nothing_goes_while_the_bot_is_off(
    db: Session, group: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer, plan = _shop(db)
    _bill(db, plan, customer, "3001")
    db.commit()
    monkeypatch.setattr(settings, "payments_bot_chat_id", "")

    assert send_receipts(db, now=utcnow()) == 0
    assert send_reports(db, now=MONDAY_NIGHT) == 0
    assert group.calls == []


def test_monday_night_brings_the_day_and_the_week_by_plan(
    db: Session, group: FakeBot
) -> None:
    start = _plan(db, "start", "Start", 1)
    pro = _plan(db, "pro", "Pro", 2)
    ali = _customer(db, "ali@client.test", "Ali")
    vali = _customer(db, "vali@client.test", "Vali")
    sunday = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    tuesday = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    _bill(db, start, ali, "4001", paid_at=sunday)
    _bill(db, start, vali, "4002", paid_at=sunday, amount_minor=29_000_000)
    _bill(db, pro, ali, "4003", paid_at=sunday, amount_minor=99_000_000)
    _bill(
        db,
        pro,
        ali,
        "4004",
        paid_at=sunday,
        amount_minor=10_000_000,
        kind=InvoiceKind.PAGES,
        pages=1,
    )
    _bill(db, pro, vali, "4005", paid_at=tuesday, amount_minor=99_000_000)
    # Not counted: refunded, held, before the week, after the day.
    _bill(db, pro, vali, "4006", paid_at=sunday, status=InvoiceStatus.REFUNDED)
    _bill(db, pro, vali, "4007", status=InvoiceStatus.HELD)
    _bill(db, pro, vali, "4008", paid_at=tuesday - timedelta(days=3))
    _bill(db, pro, vali, "4009", paid_at=MONDAY_NIGHT)
    db.commit()

    assert send_reports(db, now=MONDAY_NIGHT) == 2
    assert send_reports(db, now=MONDAY_NIGHT + timedelta(hours=1)) == 0

    day, week = [t.replace("\xa0", " ") for t in group.texts()]
    assert "Kunlik hisobot · 01.11.2026" in day
    assert "Jami: <b>1 870 000 so'm</b>" in day
    assert "To'lovlar: 4 ta · 2 kishi" in day
    assert "• Start — 2 kishi · 780 000 so'm" in day
    assert "• Pro — 1 kishi · 990 000 so'm" in day
    assert "• Qo'shimcha sahifa — 1 kishi · 100 000 so'm" in day
    assert day.index("Start") < day.index("Pro") < day.index("Qo'shimcha")

    assert "Haftalik hisobot · 26.10 – 01.11.2026" in week
    assert "To'lovlar: 5 ta · 2 kishi" in week
    assert "• Pro — 2 kishi · 1 980 000 so'm" in week


def test_the_first_brings_the_month_and_a_quiet_day_says_so(
    db: Session, group: FakeBot
) -> None:
    pro = _plan(db, "pro", "Pro", 1)
    ali = _customer(db, "ali@client.test", "Ali")
    _bill(db, pro, ali, "5001", paid_at=datetime(2026, 10, 5, 10, tzinfo=UTC))
    _bill(db, pro, ali, "5002", paid_at=datetime(2026, 10, 20, 10, tzinfo=UTC))
    db.commit()

    assert send_reports(db, now=FIRST_NIGHT) == 2

    day, month = [t.replace("\xa0", " ") for t in group.texts()]
    assert "Kunlik hisobot · 31.10.2026" in day
    assert "To'lov bo'lmadi." in day
    assert "Oylik hisobot · Oktabr 2026" in month
    assert "• Pro — 1 kishi (2 ta to'lov) · 980 000 so'm" in month


def test_no_report_after_the_early_morning(db: Session, group: FakeBot) -> None:
    assert send_reports(db, now=MONDAY_NIGHT + timedelta(hours=6)) == 0
    assert group.calls == []
