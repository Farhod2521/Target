"""The office's Statistika screen: the plan ladder and its colours, first and
repeat buyers, "doimiy" customers, Start to Standart and where the rest stop,
the sign-up path, the assistant's cost per customer a month, the businesses
and who the customers are; who may read it; and that the number of queries
does not grow with the number of customers."""

import typing
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from googleadskit import PROVIDER as GOOGLE
from metaads import PROVIDER
from pydantic import BaseModel
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.audit.models import LLMCall
from app.modules.backoffice.constants import Role
from app.modules.backoffice.schemas import StatsOut
from app.modules.billing.constants import (
    InvoiceKind,
    InvoiceStatus,
    SubscriptionStatus,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.businesses.models import Business, BusinessCategory, CustomCategory
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.leads.models import Lead
from tests.pg.test_office_actions import _staff

URL = "/api/v1/office/stats"
DAY = timedelta(days=1)


def _plan(db: Session, code: str, name: str, price: int) -> Plan:
    found = db.scalar(select(Plan).where(Plan.code == code))
    if found:
        return found
    plan = Plan(code=code, name=name, price=price, currency="UZS", period_days=30,
                max_adsets=5, llm_cost_limit_minor=1000)  # fmt: skip
    db.add(plan)
    db.flush()
    return plan


def _person(db: Session, email: str, *, joined: datetime | None = None,
            **fields: Any) -> User:  # fmt: skip
    user = User(email=email, full_name=email.split("@")[0], password="!",
                date_joined=joined or utcnow() - 60 * DAY, **fields)  # fmt: skip
    db.add(user)
    db.flush()
    return user


def _paid(db: Session, plan: Plan, owner: User | None, ago: float, *,
          amount: int = 100, email: str = "", **fields: Any) -> None:  # fmt: skip
    number = f"TS-{uuid.uuid4().hex[:12]}"
    paid = utcnow() - timedelta(days=ago)
    db.add(Invoice(owner_id=owner.id if owner else None, former_email=email,
                   number=number, plan_id=plan.id, amount_minor=amount,
                   currency="UZS", period_days=30, expires_at=paid + 30 * DAY,
                   status=fields.pop("status", InvoiceStatus.PAID), paid_at=paid,
                   created_at=paid, **fields))  # fmt: skip
    db.flush()


def _live(db: Session, owner: User, plan: Plan, *, days: int = 20) -> None:
    now = utcnow()
    db.add(Subscription(owner_id=owner.id, plan_id=plan.id,
                        status=SubscriptionStatus.ACTIVE, started_at=now - DAY,
                        expires_at=now + days * DAY))  # fmt: skip


def _launched(db: Session, owner: User, *, lead: bool) -> None:
    connection = ProviderConnection(
        owner_id=owner.id, provider=PROVIDER, external_user_id=f"fb-{owner.email}",
        token_encrypted=b"x", token_fingerprint=owner.email[:32],
    )  # fmt: skip
    db.add(connection)
    db.flush()
    account = AdAccount(owner_id=owner.id, provider=PROVIDER,
                        external_id=f"act_{owner.email}", connection_id=connection.id,
                        name="a", currency="USD", timezone="Asia/Tashkent")  # fmt: skip
    db.add(account)
    db.flush()
    db.add(CampaignLaunch(owner_id=owner.id, ad_account_id=account.id,
                          provider=PROVIDER, status="created"))  # fmt: skip
    if lead:
        now = utcnow()
        db.add(Lead(owner_id=owner.id, provider=PROVIDER, submitted_at=now,
                    received_at=now))  # fmt: skip
    db.flush()


def _ai(db: Session, owner: User, micros: int, ago: float = 1) -> None:
    db.add(LLMCall(owner_id=owner.id, purpose="chat", model="claude-x",
                   input_tokens=1000, output_tokens=100, cost_micros=micros,
                   created_at=utcnow() - timedelta(days=ago)))  # fmt: skip


def _world(db: Session) -> dict[str, User]:
    start = _plan(db, "start", "Start", 100)
    standart = _plan(db, "standart", "Standart", 300)
    pro = _plan(db, "pro", "Pro", 500)
    people: dict[str, User] = {}
    # Start, then Standart: yellow, and moved on.
    people["climber"] = climber = _person(db, "climber@c.test", role="targetolog",
                                          phone="+998900000001")  # fmt: skip
    _paid(db, start, climber, 45)
    _paid(db, standart, climber, 15, amount=300)
    _live(db, climber, standart)
    # Start only, ran out, never touched Meta: red, lost at "meta".
    people["red"] = red = _person(db, "red@c.test", joined=utcnow() - 3 * DAY)
    _paid(db, start, red, 40)
    # A Google Ads connection is not Meta: red still stopped at "meta".
    db.add(ProviderConnection(owner_id=red.id, provider=GOOGLE, external_user_id="g-red",
                              token_encrypted=b"x", token_fingerprint="g-red"))  # fmt: skip
    # Standart three times in a row: green and "doimiy".
    people["loyal"] = loyal = _person(db, "loyal@c.test", role="business_owner")
    for ago in (85, 55, 25):
        _paid(db, standart, loyal, ago, amount=300)
    _live(db, loyal, standart)
    # One Pro bill: green, not "doimiy".
    people["pro"] = top = _person(db, "pro@c.test", role="business_owner")
    # A renewal bill carrying an extra page: the page money is not plan money.
    _paid(db, pro, top, 5, amount=600, pages=1, pages_minor=100)
    _live(db, top, pro)
    # Start two days ago: still inside it.
    people["fresh"] = fresh = _person(db, "fresh@c.test", joined=utcnow() - 2 * DAY)
    _paid(db, start, fresh, 2)
    # Start, launched, got a lead, opened a Standart bill and never paid it.
    people["tried"] = tried = _person(db, "tried@c.test", prepared_at=utcnow())
    _paid(db, start, tried, 38)
    _launched(db, tried, lead=True)
    number = f"TS-{uuid.uuid4().hex[:12]}"
    db.add(Invoice(owner_id=tried.id, number=number, plan_id=standart.id,
                   amount_minor=300, currency="UZS", period_days=30,
                   expires_at=utcnow() + DAY, status=InvoiceStatus.EXPIRED))  # fmt: skip
    # A deleted account's Start: still counted, by its email.
    _paid(db, start, None, 33, email="Gone@C.test")
    # A gift and a seats bill are not plan sales.
    _paid(db, standart, climber, 3, amount=0)
    _paid(db, standart, climber, 3, amount=50, kind=InvoiceKind.SEATS)
    # Staff are left out of everything.
    staffer = _person(db, "staffer@office.test", is_staff=True)
    _paid(db, pro, staffer, 4, amount=500)
    _ai(db, staffer, 9_000_000)
    # The assistant: climber in two months, loyal in one.
    _ai(db, climber, 2_000_000, ago=1)
    _ai(db, climber, 4_000_000, ago=40)
    _ai(db, loyal, 6_000_000, ago=1)
    # Businesses.
    food = BusinessCategory(key="food", label_uz="Ovqat", preset_key="food")
    db.add(food)
    db.flush()
    db.add(Business(timezone="Asia/Tashkent", user_id=climber.id, name="Somsa", direction_id=food.id,
                    city=" toshkent "))  # fmt: skip
    db.add(Business(timezone="Asia/Tashkent", user_id=loyal.id, name="Non", direction_id=food.id,
                    city="Toshkent"))  # fmt: skip
    own = CustomCategory(owner_id=red.id, label="Tikuvchilik")
    db.add(own)
    db.flush()
    db.add(
        Business(
            timezone="Asia/Tashkent",
            user_id=red.id,
            name="Tikuv",
            custom_category_id=own.id,
        )
    )
    db.commit()
    return people


def test_statistika_figures(client: TestClient, db: Session) -> None:
    _world(db)
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    seen = client.get(URL, headers=finance, params={"period": "year"})
    assert seen.status_code == 200, seen.text
    body = seen.json()

    StatsOut.model_validate(body)
    _every_field_sent(StatsOut, body)

    head = {row["key"]: row for row in body["headline"]}
    assert head["first_buyers"]["value"] == 7
    assert head["reached_green"]["value"] == 2
    assert head["ai_per_customer_month_micros"]["value"] == 4_000_000
    bars = body["series"]["bars"]
    assert body["series"]["unit"] == "month" and len(bars) == utcnow().month
    assert sum(bar["first_buyers"] for bar in bars) == 7
    assert sum(bar["plan_takings_minor"] for bar in bars) == 100 * 5 + 300 * 4 + 500

    states = {row["key"]: row["customers"] for row in body["statuses"]["rows"]}
    assert states == {"paying": 3, "trial": 0, "ended": 0, "never": 3}
    ending = body["statuses"]
    assert (ending["ending_7"], ending["ending_30"], ending["ending_30_with_card"]) == (
        0,
        3,
        0,
    )

    ladder = {row["key"]: row["customers"] for row in body["ladder"]["segments"]}
    # red: red, fresh, tried, the deleted one; yellow: climber; green: loyal, pro.
    assert ladder == {"red": 4, "yellow": 1, "green": 2}
    assert body["ladder"]["total"] == 7
    assert body["ladder"]["yellow_from_start"] == 1

    plans = {row["code"]: row for row in body["plans"]["rows"]}
    assert plans["start"]["bills"] == 5 and plans["start"]["first_time"] == 5
    assert plans["standart"]["bills"] == 4, "the gift and the seats bill are not sales"
    assert plans["standart"]["same_plan_again"] == 2
    assert plans["standart"]["third_or_later"] == 1
    assert plans["pro"]["buyers"] == 1, "the staff Pro bill is left out"
    times = {row["key"]: row["customers"] for row in body["plans"]["times"]}
    assert times == {"1": 5, "2": 1, "3+": 1}

    loyal = body["loyal"]
    assert (loyal["customers"], loyal["still_live"], loyal["run"]) == (1, 1, 3)
    assert loyal["plans"] == [{"name": "Standart", "customers": 1}]

    keeping = body["keeping"]
    assert (keeping["paid_at_start"], keeping["lost"]) == (0, 0), (
        "nobody was paid up on 1 January"
    )
    assert keeping["churn_pct"] is None
    assert keeping["came_back"] == 0, "a renewal on the day it ran out is not a gap"
    august = next(row for row in keeping["cohorts"] if row["customers"] == 1
                  and row["kept_pct"][0] is not None)  # fmt: skip
    assert august["kept_pct"][:2] == [100.0, 100.0], "loyal renewed every month"

    start = body["start"]
    assert (start["started"], start["in_start"], start["moved"]) == (5, 1, 1)
    assert start["due"] == 4 and start["moved_pct"] == 25.0
    reasons = {row["key"]: row["customers"] for row in start["lost_reasons"]}
    assert reasons["deleted"] == 1 and reasons["meta"] == 1 and reasons["tried"] == 1
    assert start["lost"] == 3

    funnel = {row["key"]: row for row in body["funnel"]["steps"]}
    assert body["funnel"]["joined"] == 6, "the staffer is not a customer"
    assert funnel["profile"]["customers"] == 6, "a later step counts the earlier ones"
    assert funnel["paid"]["customers"] == 6 and funnel["paid"]["dropped"] == 0
    assert funnel["standard"]["customers"] == 3 and funnel["standard"]["dropped"] == 3
    assert funnel["green"]["customers"] == 2

    ai = body["ai"]
    assert ai["cost_micros"] == 12_000_000 and ai["staff_cost_micros"] == 9_000_000
    assert ai["customers"] == 2
    assert ai["customer_months"] in (2, 3), "climber's two calls may share a month"
    assert ai["micros_per_unit"] == 100_000_000
    assert ai["top"][0]["email"] in ("climber@c.test", "loyal@c.test")

    business = body["businesses"]
    assert business["total"] == 3 and business["owners"] == 3
    directions = {row["key"]: row for row in business["directions"]}
    assert directions["food"]["businesses"] == 2
    assert directions["food"]["paying_owners"] == 2
    assert directions["custom"]["label"] == "O'zi yozgan"
    assert business["custom_top"] == [
        {"label": "Tikuvchilik", "businesses": 1, "share_pct": 33.3}
    ]
    assert business["cities"][0] == {"label": "Toshkent", "businesses": 2,
                                     "share_pct": 66.7}  # fmt: skip

    roles = {row["key"]: row for row in body["people"]["roles"]["rows"]}
    assert roles["business_owner"]["customers"] == 2
    assert roles["business_owner"]["paying_now"] == 2

    money = body["money"]
    assert money["takings_minor"] == 100 * 5 + 300 * 4 + 600 + 50
    kinds = {row["key"]: row["amount_minor"] for row in money["kinds"]}
    assert kinds == {"plan": 100 * 5 + 300 * 4 + 500, "pages": 100, "seats": 50}
    assert plans["pro"]["amount_minor"] == 500, (
        "the page on the Pro bill is not Pro money"
    )

    # 30 days: churn counts only who was paid up when the window began (climber, red,
    # tried, the deleted one, loyal); of them red, tried and the deleted one ran out.
    month = client.get(URL, headers=finance, params={"period": "30"}).json()["keeping"]
    assert (month["paid_at_start"], month["lost"], month["churn_pct"]) == (5, 3, 60.0)
    assert month["paid_at_end"] == 4, "climber, loyal, pro and fresh"

    # A week holds no whole month: the AI figure is brought to 30 days, 8 000 000 micros
    # for 2 customers over 7 days.
    week = client.get(URL, headers=finance, params={"period": "7"}).json()
    rate = {row["key"]: row["value"] for row in week["headline"]}[
        "ai_per_customer_month_micros"
    ]
    assert rate == week["ai"]["per_customer_month_micros"] == 8_000_000 * 30 // (2 * 7)
    assert money["plan_payers"] == 7
    assert money["paying_now"] == 3 and money["autopay_now"] == 0

    lost = client.get(f"{URL}/start-lost", headers=finance,
                      params={"period": "year", "reason": "meta"})  # fmt: skip
    assert lost.status_code == 200, lost.text
    assert [row["email"] for row in lost.json()["rows"]] == ["red@c.test"]
    gone = client.get(f"{URL}/start-lost", headers=finance,
                      params={"period": "year", "reason": "deleted"}).json()  # fmt: skip
    assert (gone["total"], gone["deleted"], gone["rows"]) == (1, 1, [])
    # A half range (what the front sends when a day is missing) is refused in words, not a 422.
    half = client.get(
        URL, headers=finance, params={"period": "range", "since": "2026-10-01"}
    )
    assert half.status_code == 200, half.text
    assert half.json()["window"]["refused"] == "Ikkala sanani ham tanlang."

    assert client.get(f"{URL}/start-lost", headers=finance,
                      params={"reason": "nope"}).status_code == 404  # fmt: skip


def _every_field_sent(model: type[BaseModel], data: Any, path: str = "") -> None:
    """The schema the front is built from promises no field the answer lacks."""
    if isinstance(data, list):
        for row in data:
            _every_field_sent(model, row, path)
        return
    assert set(model.model_fields) == set(data), path
    for key, spec in model.model_fields.items():
        for kind in (spec.annotation, *typing.get_args(spec.annotation)):
            for inner in (kind, *typing.get_args(kind)):
                if isinstance(inner, type) and issubclass(inner, BaseModel):
                    _every_field_sent(inner, data[key], f"{path}.{key}")


def test_only_money_roles_read_it(client: TestClient, db: Session) -> None:
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, owner = _staff(db, Role.OWNER, email="owner@office.test")
    assert client.get(URL, headers=support).status_code == 404
    assert (
        client.get(f"{URL}/start-lost?reason=meta", headers=support).status_code == 404
    )
    assert client.get(URL, headers=owner).status_code == 200


def test_queries_do_not_grow_with_customers(client: TestClient, db: Session) -> None:
    _world(db)
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    engine = db.get_bind()

    def counted() -> int:
        seen: list[str] = []

        def note(*args: Any) -> None:
            seen.append(args[2])

        event.listen(engine, "before_cursor_execute", note)
        try:
            assert client.get(URL, headers=finance).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", note)
        return len(seen)

    before = counted()
    assert before < 45, before
    standart = _plan(db, "standart", "Standart", 300)
    for number in range(15):
        more = _person(db, f"more{number}@c.test", role="targetolog")
        _paid(db, standart, more, 10, amount=300)
        _live(db, more, standart)
        _ai(db, more, 1_000_000)
        db.add(Business(timezone="Asia/Tashkent", user_id=more.id, name=f"B{number}"))
    db.commit()
    assert counted() == before, before
