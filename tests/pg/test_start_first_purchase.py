"""Start is sold once, as the very first purchase, and at its own price:
an account that has had any plan is not offered it again, and no promo code
comes off it."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing import selectors
from app.modules.billing import services as billing
from app.modules.billing.constants import WalletChoice
from app.modules.billing.exceptions import PlanAlreadyBought, PromoNotApplicable
from app.modules.billing.models import Plan
from app.modules.billing.services import grants
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_offer import START, _codes, _start
from tests.pg.test_boards_sales import _client, _paid, _plan
from tests.pg.test_crm_http import _auth


def _plans(db: Session) -> tuple[Plan, Plan]:
    full, start = _plan(db), _start(db)
    db.commit()
    return full, start


def _offered(db: Session, owner: User) -> list[str]:
    return [plan.code for plan in selectors.sellable_plans(db, owner=owner)]


def _paywall(client: TestClient, owner: User, **params: Any) -> dict[str, Any]:
    answer = client.get(
        "/api/v1/billing/paywall",
        params={"plan": "start", **params},
        headers=_auth(owner),
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_start_is_offered_only_before_the_first_plan(db: Session) -> None:
    _full, start = _plans(db)
    new = _client(db, "new@shop.test")
    assert "start" in _offered(db, new)

    # Bought Standart, never Start: Start is gone all the same.
    buyer = _client(db, "buyer@shop.test")
    _paid(db, buyer)
    assert "start" not in _offered(db, buyer)
    assert "standart" in _offered(db, buyer)
    assert selectors.sellable_plan(db, code="start", owner=buyer) is None
    with pytest.raises(PlanAlreadyBought):
        billing.create_invoice(db, owner=buyer, plan=start, now=utcnow())


def test_a_plan_the_office_gave_closes_start_too(db: Session) -> None:
    full, start = _plans(db)
    given = _client(db, "given@shop.test")
    _staff(db, "boss@office.test", superuser=True)
    actor = db.scalar(select(User).where(User.email == "boss@office.test"))
    assert actor is not None
    grants.grant_plan(
        db, owner=given, plan=full, actor=actor, reason="sinov", now=utcnow()
    )
    db.commit()
    assert "start" not in _offered(db, given)
    with pytest.raises(PlanAlreadyBought):
        billing.create_invoice(db, owner=given, plan=start, now=utcnow())


def test_no_promo_code_comes_off_start(client: TestClient, db: Session) -> None:
    _full, start = _plans(db)
    _codes(db)
    owner = _client(db, "promo@shop.test")
    now = utcnow()
    invoice = billing.create_invoice(db, owner=owner, plan=start, now=now)
    db.commit()
    with pytest.raises(PromoNotApplicable):
        billing.price_invoice(
            db, invoice=invoice, promo_code="BIG30", wallet=WalletChoice.KEEP, now=now
        )
    db.rollback()
    plain = billing.price_invoice(
        db, invoice=invoice, promo_code="", wallet=WalletChoice.KEEP, now=now
    )
    assert plain.amount_minor == START
    db.commit()

    shown = _paywall(client, owner, promo="BIG30")
    assert "promo_quote" not in shown and shown["promo_error"]
    assert shown["chosen"]["promo_minor"] == 0
    assert shown["chosen"]["due_minor"] == START
    # The same code still comes off a full plan.
    full = client.get(
        "/api/v1/billing/paywall",
        params={"plan": "standart", "promo": "BIG30"},
        headers=_auth(owner),
    ).json()
    assert full["promo_quote"]["percent"] == 30
