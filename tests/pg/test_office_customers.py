"""The office's customer list: who is on it, what each chip finds, what a row says."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import utcnow
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.backoffice.constants import Role
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.sales.models import SalesClaim

URL = "/api/v1/office/customers"


def _staff(db: Session, role: Role, *, email: str) -> tuple[User, dict[str, str]]:
    member = User(
        email=email, full_name=email, password="!", is_staff=True, date_joined=utcnow()
    )
    db.add(member)
    db.flush()
    group = db.scalar(select(Group).where(Group.name == str(role)))
    if group is None:
        group = Group(name=str(role))
        db.add(group)
        db.flush()
    db.add(UserGroup(user_id=member.id, group_id=group.id))
    db.commit()
    token = tokens.issue(subject=str(member.id), kind="access", now=utcnow())
    return member, {"Authorization": f"Bearer {token}"}


def _plan(db: Session) -> Plan:
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
    db.flush()
    return plan


def _customer(db: Session, email: str, *, days_ago: int = 1, **fields: object) -> User:
    user = User(
        email=email,
        full_name=email.split("@")[0].title(),
        password="!",
        date_joined=utcnow() - timedelta(days=days_ago),
        **fields,
    )
    db.add(user)
    db.flush()
    return user


def _subscribe(
    db: Session, user: User, plan: Plan, *, status: str, days: int
) -> Subscription:
    now = utcnow()
    row = Subscription(
        owner_id=user.id,
        plan_id=plan.id,
        status=status,
        started_at=now - timedelta(days=30),
        expires_at=now + timedelta(days=days),
        setup_completed_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _world(db: Session) -> dict[str, User]:
    plan = _plan(db)
    active = _customer(db, "active@shop.test", days_ago=5, phone="+998901112233")
    _subscribe(db, active, plan, status=SubscriptionStatus.ACTIVE, days=20)
    trial = _customer(db, "trial@shop.test", days_ago=4)
    _subscribe(db, trial, plan, status=SubscriptionStatus.TRIAL, days=3)
    lapsed = _customer(db, "lapsed@shop.test", days_ago=3)
    _subscribe(db, lapsed, plan, status=SubscriptionStatus.ACTIVE, days=-2)
    never = _customer(db, "never@shop.test", days_ago=2)
    _customer(db, "manager@shop.test", crm_owner_id=active.id)
    db.add(
        Invoice(
            owner_id=active.id,
            number="TA-0001",
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
    return {"active": active, "trial": trial, "lapsed": lapsed, "never": never}


def _emails(body: dict) -> list[str]:  # type: ignore[type-arg]
    return [row["customer"]["email"] for row in body["rows"]]


def test_the_list_holds_customers_only_and_says_their_term(
    client: TestClient, db: Session
) -> None:
    people = _world(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _, seller = _staff(db, Role.SALES, email="seller@office.test")

    assert client.get(URL, headers=seller).status_code == 404
    listed = client.get(URL, headers=support)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert _emails(body) == [
        "never@shop.test",
        "lapsed@shop.test",
        "trial@shop.test",
        "active@shop.test",
    ]
    assert body["total"] == 4 and not body["has_more"]
    rows = {row["customer"]["email"]: row for row in body["rows"]}
    assert rows["active@shop.test"]["term"]["state"] == "active"
    assert rows["active@shop.test"]["term"]["plan"]["code"] == "pro"
    assert rows["active@shop.test"]["paid_total"] == [
        {"currency": "UZS", "amount_minor": 49000000}
    ]
    assert rows["lapsed@shop.test"]["term"]["state"] == "lapsed"
    assert rows["lapsed@shop.test"]["term"]["ended_on"] is not None
    assert rows["never@shop.test"]["term"] == {
        "state": "never",
        "label": "Obuna olmagan",
        "plan": None,
        "days_left": None,
        "expires_at": None,
        "ended_on": None,
    }
    assert rows["trial@shop.test"]["trouble"]["kind"] == "expiring"
    assert people["active"].id


def test_search_and_chips(client: TestClient, db: Session) -> None:
    _world(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    def found(query: str) -> list[str]:
        answer = client.get(f"{URL}?{query}", headers=support)
        assert answer.status_code == 200, answer.text
        return _emails(answer.json())

    assert found("q=TRIAL@") == ["trial@shop.test"]
    assert found("q=90 111 22 33") == ["active@shop.test"]
    assert found("q=TA-0001") == ["active@shop.test"]
    assert found("state=active") == ["active@shop.test"]
    assert found("state=trial") == ["trial@shop.test"]
    assert found("state=lapsed") == ["lapsed@shop.test"]
    assert found("state=never") == ["never@shop.test"]
    assert found("state=expiring") == ["trial@shop.test"]
    assert found("plan=pro&sort=expires") == [
        "trial@shop.test",
        "active@shop.test",
        "lapsed@shop.test",
    ]


def test_a_blocked_ad_account_is_trouble_and_a_manager_is_named(
    client: TestClient, db: Session
) -> None:
    people = _world(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    seller, _ = _staff(db, Role.SALES, email="seller@office.test")
    owner = people["active"]
    link = ProviderConnection(
        owner_id=owner.id, provider="meta", token_encrypted=b"x", status="active"
    )
    db.add(link)
    db.flush()
    db.add(
        AdAccount(
            owner_id=owner.id,
            provider="meta",
            external_id="act_1",
            connection_id=link.id,
            is_active=True,
            payment_due=True,
        )
    )
    now = utcnow()
    db.add(
        SalesClaim(
            owner_id=owner.id,
            manager_id=seller.id,
            claimed_at=now,
            expires_at=now + timedelta(days=3),
        )
    )
    db.commit()

    body = client.get(f"{URL}?state=trouble", headers=support).json()
    assert _emails(body) == ["trial@shop.test", "active@shop.test"]
    row = body["rows"][1]
    assert row["trouble"]["kind"] == "payment_due"
    assert row["trouble"]["urgent"] is True
    assert row["sales_manager"]["email"] == "seller@office.test"
    assert any(choice["value"] == str(seller.id) for choice in body["managers"])

    held = client.get(f"{URL}?manager={seller.id}", headers=support).json()
    assert _emails(held) == ["active@shop.test"]
    free = client.get(f"{URL}?manager=none", headers=support).json()
    assert "active@shop.test" not in _emails(free) and len(free["rows"]) == 3
    assert client.get(f"{URL}?q=act_1", headers=support).json()["total"] == 1


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_the_card_says_everything_and_no_secret(
    client: TestClient, db: Session
) -> None:
    people = _world(db)
    support, headers = _staff(db, Role.SUPPORT, email="support@office.test")
    owner = people["active"]
    link = ProviderConnection(
        owner_id=owner.id,
        provider="meta",
        token_encrypted=b"secret",
        token_fingerprint="abc",
        status="active",
        external_user_name="Shop Owner",
    )
    db.add(link)
    db.commit()

    card = client.get(f"{URL}/{owner.id}", headers=headers)
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["profile"]["email"] == "active@shop.test"
    assert body["profile"]["phone"] == "+998901112233"
    assert body["subscription"]["plan"]["code"] == "pro"
    assert body["subscription"]["days_left"] in (19, 20)
    assert body["lapsed"] is None
    assert body["meta"]["name"] == "Shop Owner"
    assert body["money"]["paid"] == [{"currency": "UZS", "amount_minor": 49000000}]
    assert body["money"]["invoices"][0]["number"] == "TA-0001"
    assert body["limits"]["crm_seats"]["used"] == 0
    assert [choice["code"] for choice in body["plan_picker"]["choices"]] == ["pro"]
    assert body["referral"]["mode"] == "auto"
    assert body["sales"]["claim"] is None
    assert [trace["kind"] for trace in body["traces"]] == ["view"]
    assert body["traces"][0]["actor"]["id"] == str(support.id)
    leaked = {
        key
        for key in _keys(body)
        if "token" in key
        or "password" in key
        or "fingerprint" in key
        or "encrypted" in key
    }
    assert leaked == set()

    again = client.get(f"{URL}/{owner.id}", headers=headers).json()
    assert len(again["traces"]) == 1

    lapsed = client.get(f"{URL}/{people['lapsed'].id}", headers=headers).json()
    assert lapsed["subscription"] is None and lapsed["lapsed"]["plan"]["code"] == "pro"

    manager_login = db.scalar(select(User).where(User.email == "manager@shop.test"))
    assert manager_login is not None
    assert client.get(f"{URL}/{manager_login.id}", headers=headers).status_code == 404
    colleague = client.get(f"{URL}/{support.id}", headers=headers)
    assert colleague.status_code == 200, colleague.text
    assert colleague.json()["profile"]["is_staff"] is True
    assert body["profile"]["is_staff"] is False


def test_the_ads_tab_reads_only_what_this_product_launched(
    client: TestClient, db: Session
) -> None:
    from tests.pg.conftest import sign_up
    from tests.pg.test_chat import _account
    from tests.pg.test_chat import _mirror as _campaigns

    sign_up(client)
    owner, account, page = _account(db)
    _campaigns(db, owner, account, page)
    db.commit()
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    month = client.get(f"{URL}/{owner.id}/ads?period=30", headers=support)
    assert month.status_code == 200, month.text
    body = month.json()
    assert body["period"] == "30" and body["running"] == 1
    [row] = body["rows"]
    assert row["campaign_external_id"] == "c_1"
    assert row["is_running"] is True
    assert row["spend_minor"] == 3500
    assert row["page"] == page.name

    today = client.get(f"{URL}/{owner.id}/ads?period=today", headers=support).json()
    assert [r["spend_minor"] for r in today["rows"]] == [0]
    assert (
        client.get(f"{URL}/{owner.id}/ads?period=nope", headers=support).json()[
            "period"
        ]
        == "month"
    )


def test_the_blocked_chip_finds_only_blocked_accounts(
    client: TestClient, db: Session
) -> None:
    people = _world(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    base = f"{URL}/{people['trial'].id}"

    def found(query: str) -> dict:  # type: ignore[type-arg]
        answer = client.get(f"{URL}?{query}", headers=support)
        assert answer.status_code == 200, answer.text
        return answer.json()

    chips = {choice["value"]: choice["label"] for choice in found("")["states"]}
    assert chips["blocked"] == "Bloklangan"
    assert found("state=blocked")["total"] == 0

    blocked = client.post(f"{base}/block", headers=support, json={"reason": "Spam"})
    assert blocked.status_code == 200, blocked.text
    body = found("state=blocked")
    assert _emails(body) == ["trial@shop.test"] and body["total"] == 1
    assert body["rows"][0]["is_blocked"] is True
    assert "trial@shop.test" in _emails(found("state=trial"))
    assert "trial@shop.test" in _emails(found(""))

    freed = client.post(f"{base}/unblock", headers=support, json={"reason": "Ok"})
    assert freed.status_code == 200, freed.text
    assert found("state=blocked")["total"] == 0


def test_the_trouble_feed_is_read_once_a_minute_and_reads_the_same(
    client: TestClient, db: Session
) -> None:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.modules.backoffice.selectors.problems import every_problem, problems

    people = _world(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    for n, email in enumerate(("a", "b", "c")):
        owner = _customer(db, f"{email}@broken.test")
        db.add(
            ProviderConnection(
                owner_id=owner.id,
                provider="meta",
                token_encrypted=b"x",
                token_fingerprint=f"f{n}",
                status="invalid",
            )
        )
    db.commit()
    now = utcnow()
    fresh = problems(db, now=now, limit=None)
    assert {p.kind for p in fresh} >= {"connection", "expiring"}

    seen: list[str] = []

    def _record(*args: object) -> None:
        seen.append(" ".join(str(args[2]).split()))

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        first = client.get(f"{URL}?state=trouble", headers=support).json()
        read_first = list(seen)
        seen.clear()
        again = client.get(f"{URL}?state=trouble", headers=support).json()
    finally:
        event.remove(Engine, "before_cursor_execute", _record)

    one_by_one = [
        sql
        for sql in read_first
        if sql.startswith("SELECT users.") and "WHERE users.id = " in sql
    ]
    assert len(one_by_one) <= 2, one_by_one
    assert len(seen) < len(read_first)
    assert _emails(first) == _emails(again)
    assert {"a@broken.test", "b@broken.test", "c@broken.test"} <= set(_emails(again))
    assert every_problem(db, now=now) == fresh
    assert people["trial"].id in {p.owner_id for p in every_problem(db, now=now)}


def test_the_staff_chip_lists_colleagues_and_only_it_does(
    client: TestClient, db: Session
) -> None:
    _world(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    def found(query: str) -> dict:  # type: ignore[type-arg]
        answer = client.get(f"{URL}?{query}", headers=support)
        assert answer.status_code == 200, answer.text
        return answer.json()

    everyone = found("")
    assert "support@office.test" not in _emails(everyone)
    assert {row["is_staff"] for row in everyone["rows"]} == {False}
    assert ("staff", "Xodimlar") in {
        (choice["value"], choice["label"]) for choice in everyone["states"]
    }
    colleagues = found("state=staff")
    assert _emails(colleagues) == ["support@office.test"]
    assert colleagues["rows"][0]["is_staff"] is True
    assert _emails(found("state=staff&q=support@")) == ["support@office.test"]
    assert found("state=staff&q=active@")["total"] == 0
