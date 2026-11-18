"""What the assistant reads about money: Meta's payment standing of each ad
account with where to settle it, and the product's own plans with today's
dollar rate - so it stops saying «I cannot see the price» or «I do not know
the rate»."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.assistant.selectors.health import account_health
from app.modules.assistant.selectors.plans import plans_text
from app.modules.billing.models import Plan
from app.modules.billing.selectors import display
from app.modules.chat.selectors.scope import current_page_scope
from core.chat.lookup_arguments import Nothing
from tests.pg.conftest import sign_up
from tests.pg.test_assistant import _ask, _Script, _with_plan
from tests.pg.test_chat import _account


@pytest.fixture(autouse=True)
def rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display, "usd_rate", lambda: (Decimal("12650.5"), "18.11.2026"))


def _health(db: Session, owner) -> str:  # type: ignore[no-untyped-def]
    return account_health(
        db, owner=owner, scope=current_page_scope(db, owner=owner), now=utcnow()
    )


def _cabinet(client: TestClient, db: Session):  # type: ignore[no-untyped-def]
    sign_up(client)
    owner, account, _page = _account(db)
    account.name = "tilla ads"
    account.currency = "USD"
    account.external_id = "act_123"
    return owner, account


def test_a_failed_payment_in_grace_names_the_debt_and_where_to_pay(
    client: TestClient, db: Session
) -> None:
    owner, account = _cabinet(client, db)
    account.standing = "payment_grace"
    account.balance_minor = 1234
    db.commit()
    text = _health(db, owner)
    assert "PROBLEM: ad account «tilla ads»" in text
    assert "grace period" in text and "still run" in text
    assert "owed to Meta: $12,34" in text
    assert "billing_hub/payment_settings/?asset_id=123" in text
    assert "«Pay now»" in text


def test_a_prepaid_account_is_told_to_add_money_not_a_card(
    client: TestClient, db: Session
) -> None:
    owner, account = _cabinet(client, db)
    account.standing = "payment_failed"
    account.prepaid = True
    db.commit()
    text = _health(db, owner)
    assert "(prepaid balance)" in text
    assert "add money to its prepaid balance" in text
    assert "«Pay now»" not in text


def test_a_used_up_spending_limit_is_named(client: TestClient, db: Session) -> None:
    owner, account = _cabinet(client, db)
    account.standing = "active"
    account.spend_cap_minor = 5000
    account.amount_spent_minor = 5000
    db.commit()
    text = _health(db, owner)
    assert "account spending limit is used up" in text
    assert "«Account spending limit»" in text


def test_a_healthy_account_says_it_can_advertise(client: TestClient, db: Session) -> None:
    owner, account = _cabinet(client, db)
    account.standing = "active"
    db.commit()
    assert "OK: ad account «tilla ads» (USD) can advertise." in _health(db, owner)


def _plan(db: Session, code: str, price: int, **fields: object) -> Plan:
    plan = Plan(
        code=code,
        name=code.title(),
        price=price,
        currency="UZS",
        period_days=30,
        max_adsets=20,
        llm_cost_limit_minor=1000,
        **fields,
    )
    db.add(plan)
    db.commit()
    return plan


def test_a_visitor_reads_the_plans_and_the_rate(db: Session) -> None:
    _plan(db, "biznes_x", 990000, included_pages=2, extra_page_price=150000)
    text = plans_text(db, owner=None, now=utcnow())
    assert "«Biznes_X»" in text
    assert "2 page(s) included" in text and "each extra page" in text
    assert "1 USD = 12 650 so'm" in text and "18.11.2026" in text
    assert "## This person" not in text


def test_the_assistant_quotes_the_plans_through_its_tool(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plan(db, "biznes_y", 790000)
    headers, _owner = _with_plan(client, db)
    script = _Script(calls=[("plans_and_prices", Nothing())])
    _ask(client, db, headers, monkeypatch, script, question="Tarif qancha turadi?")
    assert "«Biznes_Y»" in script.seen[0]
    assert "## This person" in script.seen[0]
    assert "1 USD = 12 650 so'm" in script.seen[0]


def test_accounts_left_out_of_the_subscription_are_named(
    client: TestClient, db: Session
) -> None:
    from app.modules.chat.selectors.lookups import answer_lookup
    from app.modules.chat.selectors.scope import asked_scopes
    from app.modules.integrations.models import AdAccount

    owner, account = _cabinet(client, db)
    db.add(
        AdAccount(
            owner_id=owner.id,
            provider=account.provider,
            external_id="act_999",
            connection_id=account.connection_id,
            name="Kiyim tavar",
            currency="USD",
            is_active=False,
        )
    )
    db.commit()
    scope, counted = asked_scopes(db, owner=owner)
    text = answer_lookup(
        db,
        owner=owner,
        name="account_overview",
        arguments=Nothing(),
        scope=scope,
        now=utcnow(),
        counted=counted,
    )
    assert "connected but not in the subscription: «Kiyim tavar» (USD)" in text
