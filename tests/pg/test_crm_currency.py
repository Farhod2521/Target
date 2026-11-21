"""The currency a pair writes its sales in: chosen by the owner, kept by
every sale already closed, and crossed at the closing day's rate wherever
sales are summed. And the daily rates themselves."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.crm.models import CrmCard, CrmMember, CrmSetup
from app.modules.metrics.models import FxRate
from app.modules.metrics.services.rates import HISTORY_DAYS, store_rates
from tests.pg.test_crm_http import CRM, _auth, _member, _owner, _running


def _currency(client: TestClient, head: dict[str, str], code: str) -> httpx.Response:
    return client.post(
        f"{CRM}/settings/currency", headers=head, json={"currency": code}
    )


def _rate(db: Session, code: str, rate: str, *, days_ago: int = 5) -> None:
    day = localtime(utcnow()).date() - timedelta(days=days_ago)
    db.add(FxRate(day=day, currency=code, rate=Decimal(rate)))
    db.commit()


def _won_column(board: dict) -> dict:  # type: ignore[type-arg]
    return next(c for c in board["columns"] if c["stage"]["kind"] == "won")


def test_the_owner_chooses_the_currency_from_the_list(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    _running(client, head)
    settings = client.get(f"{CRM}/settings", headers=head).json()
    assert settings["setup"]["currency"] == "USD"
    assert [c["value"] for c in settings["currency_choices"]] == [
        "UZS",
        "USD",
        "EUR",
        "RUB",
        "KZT",
    ]

    saved = _currency(client, head, " uzs ")

    assert saved.status_code == 200
    assert saved.json()["setup"]["currency"] == "UZS"
    refused = _currency(client, head, "XXX")
    assert refused.status_code == 400
    assert refused.json()["code"] == "unknown_currency"
    assert db.scalar(select(CrmSetup.currency)) == "UZS"


def test_a_manager_cannot_change_the_currency(client: TestClient, db: Session) -> None:
    head = _auth(_owner(db))
    _running(client, head)
    _, manager = _member(client, head, "m1@example.com")
    new = "Yz4$kW8nRt2q"
    client.post(
        f"{CRM}/password", headers=manager, json={"password": new, "again": new}
    )

    assert _currency(client, manager, "UZS").status_code == 404
    assert db.scalar(select(CrmSetup.currency)) == "USD"


def test_fixed_pay_of_the_old_currency_is_cleared_and_percent_stays(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    _running(client, head)
    added, _ = _member(client, head, "m2@example.com")
    saved = client.put(
        f"{CRM}/settings/members/{added['id']}",
        headers=head,
        json={"name": "m2", "kpi_fix": "500", "kpi_percent": "5"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["kpi_currency"] == "USD"

    assert _currency(client, head, "UZS").status_code == 200

    db.expire_all()
    member = db.scalar(select(CrmMember))
    assert member is not None
    assert (member.kpi_fix_minor, member.kpi_currency, member.kpi_percent) == (
        None,
        "",
        5,
    )


def test_a_closed_sale_keeps_its_currency_and_sums_at_its_days_rate(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    first, second = (c["id"] for c in board["columns"][0]["cards"][:2])
    assert client.post(
        f"{CRM}/cards/{first}/win", headers=head, json={"amount": "150"}
    ).is_success
    _rate(db, "USD", "12000")
    assert _currency(client, head, "UZS").status_code == 200
    assert client.post(
        f"{CRM}/cards/{second}/win", headers=head, json={"amount": "500000"}
    ).is_success

    board = client.get(CRM, headers=head).json()
    stats = client.get(f"{CRM}/stats", headers=head).json()

    kept = db.scalar(select(CrmCard).where(CrmCard.currency == "USD"))
    assert kept is not None and kept.won_amount_minor == 15000
    # $150 at 12 000 = 1 800 000 so'm, and 500 000 so'm typed after the change.
    assert board["currency"] == "UZS"
    assert _won_column(board)["won_minor"] == 230_000_000
    assert stats["currency"] == "UZS"
    assert stats["totals"]["won"] == 2
    assert stats["totals"]["revenue_minor"] == 230_000_000
    assert stats["totals"]["revenue_unpriced"] == 0
    assert stats["totals"]["avg_deal_minor"] == 115_000_000
    assert stats["ads"][0]["revenue_minor"] == 230_000_000


def test_a_sale_no_rate_prices_is_counted_apart_never_added_as_it_stands(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    first, second = (c["id"] for c in board["columns"][0]["cards"][:2])
    client.post(f"{CRM}/cards/{first}/win", headers=head, json={"amount": "150"})
    assert _currency(client, head, "UZS").status_code == 200
    client.post(f"{CRM}/cards/{second}/win", headers=head, json={"amount": "500000"})

    board = client.get(CRM, headers=head).json()
    totals = client.get(f"{CRM}/stats", headers=head).json()["totals"]

    assert _won_column(board)["won_minor"] == 50_000_000
    assert totals["revenue_minor"] == 50_000_000
    assert totals["revenue_unpriced"] == 1
    assert totals["avg_deal_minor"] == 50_000_000


def test_rates_are_read_newest_first_and_a_day_off_is_kept_under_its_own_date(
    db: Session,
) -> None:
    now = datetime.fromisoformat("2026-11-16T10:00:00+00:00")
    today = localtime(now).date()
    off = today - timedelta(days=1)
    asked: list[date] = []

    def fetch(day: date) -> list[tuple[date, str, Decimal]]:
        asked.append(day)
        # The bank answers the day off with the rate set the day before it.
        set_on = day - timedelta(days=1) if day == off else day
        return [(set_on, "USD", Decimal("12000")), (set_on, "EUR", Decimal("13000"))]

    added = store_rates(db, now=now, fetch=fetch, back=2)

    # Today first; the day before the day off came with the day off's answer.
    assert asked == [today, off]
    assert added == 6
    held = set(db.scalars(select(FxRate.day).where(FxRate.currency == "USD")))
    assert held == {today, off, off - timedelta(days=1)}
    # Every day asked has a row of its own: nothing is asked for twice.
    asked.clear()
    assert store_rates(db, now=now, fetch=fetch, back=2) == 0
    assert asked == []


def test_a_silent_bank_stops_the_run_and_the_next_one_goes_on(db: Session) -> None:
    now = datetime.fromisoformat("2026-11-16T10:00:00+00:00")
    today = localtime(now).date()
    asked: list[date] = []

    def fetch(day: date) -> list[tuple[date, str, Decimal]]:
        asked.append(day)
        if len(asked) == 3:
            raise httpx.ConnectError("down")
        return [(day, "USD", Decimal("12000"))]

    added = store_rates(db, now=now, fetch=fetch, back=5)

    assert (added, asked) == (
        2,
        [today, today - timedelta(days=1), today - timedelta(days=2)],
    )
    # The next run goes on from the day that failed, skipping none.
    again: list[date] = []

    def answering(day: date) -> list[tuple[date, str, Decimal]]:
        again.append(day)
        return [(day, "USD", Decimal("12000"))]

    store_rates(db, now=now, fetch=answering, back=5)
    assert again == [today - timedelta(days=n) for n in (2, 3, 4, 5)]


def test_the_past_year_is_reached_and_no_further(db: Session) -> None:
    now = datetime.fromisoformat("2026-11-16T10:00:00+00:00")
    today = localtime(now).date()
    asked: list[date] = []

    def fetch(day: date) -> list[tuple[date, str, Decimal]]:
        asked.append(day)
        return [(day, "USD", Decimal("12000"))]

    store_rates(db, now=now, fetch=fetch)

    assert asked[0] == today
    assert asked[-1] == today - timedelta(days=HISTORY_DAYS)
    assert len(asked) == HISTORY_DAYS + 1
