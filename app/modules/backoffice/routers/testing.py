"""«Testing» in the office, as JSON. The superuser alone.

``POST /payments`` makes a real trial payment of ``usd`` dollars (charged
in so'm at the Central Bank's rate): ``method`` ``card`` takes it from the
superuser's own saved card, ``page`` answers ``page_url``, Multicard's
checkout page to pay it on. A card charge Multicard texted a code for
stands ``code``: ``POST /payments/{id}/confirm`` with it. ``POST
/payments/{id}/check`` reads it again from Multicard, ``POST
/payments/{id}/refund`` returns the money to the card.
"""

import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.autopay.selectors import active_card
from app.modules.backoffice.permissions import superuser_required
from app.modules.backoffice.services import testing
from app.modules.billing.models import TestCard, TestPayment

router = APIRouter(prefix="/testing")
Superuser = Annotated[User, Depends(superuser_required)]

STATUS_LABELS = {
    "created": "Yaratildi",
    "waiting": "Kutilmoqda",
    "code": "SMS kod kutilmoqda",
    "paid": "To'landi",
    "failed": "O'tmadi",
    "refunded": "Qaytarildi",
}


class TestStartIn(BaseModel):
    method: str = Field(
        description="`card` (your saved card) or `page` (Multicard's page)."
    )
    usd: str = Field("1", description="Dollars, e.g. `1` or `0.50`.")
    card_id: str = Field(
        "", description="With `card`: a test card's id; empty: the account's own card."
    )


class TestCardIn(BaseModel):
    phone: str = Field(
        "", description="The card's SMS phone (Humo needs it); empty: none is sent."
    )
    card_type: str = Field(
        "", description="`humo` asks the phone; any other card is bound without."
    )


class TestCodeIn(BaseModel):
    code: str


def _out(row: TestPayment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "number": row.number,
        "method": row.method,
        "usd": f"{Decimal(row.usd_cents) / 100:.2f}",
        "amount_uzs": row.amount_uzs,
        "rate": row.rate,
        "rate_date": row.rate_date,
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status),
        "page_url": row.page_url,
        "card_pan": row.card_pan,
        "card_ps": row.card_ps,
        "detail": row.detail,
        "external_id": row.external_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "paid_at": row.paid_at.isoformat() if row.paid_at else None,
        "refunded_at": row.refunded_at.isoformat() if row.refunded_at else None,
        "can_refund": row.status == "paid" and bool(row.external_id),
    }


def _card_out(card: TestCard) -> dict[str, Any]:
    return {"id": str(card.id), "pan": card.pan, "ps": card.ps, "holder": card.holder}


def _cents(usd: str) -> int:
    try:
        value = Decimal(usd.replace(",", ".").strip())
    except InvalidOperation as exc:
        raise testing.TestingRefused(
            "Summani raqamda yozing, masalan 1 yoki 0.50."
        ) from exc
    return int((value * 100).to_integral_value())


@router.get("")
def overview(db: Db, user: Superuser) -> dict[str, Any]:
    """The rate, the superuser's own card, and the last trial payments."""
    rate = testing.current_rate()
    card = active_card(db, owner=user)
    return {
        "rate": {"uzs_per_usd": str(rate.uzs_per_usd), "date": rate.date}
        if rate
        else None,
        "card": {"pan": card.pan, "ps": card.ps, "holder": card.holder}
        if card is not None
        else None,
        "test_cards": [
            _card_out(card)
            for card in testing.bound_test_cards(db, actor=user, now=utcnow())
        ],
        "rows": [_out(row) for row in testing.recent(db)],
    }


@router.post("/payments")
def start(db: Db, user: Superuser, body: TestStartIn) -> dict[str, Any]:
    row = testing.start(
        db,
        actor=user,
        method=body.method,
        usd_cents=_cents(body.usd),
        card_id=body.card_id,
        now=utcnow(),
    )
    return _out(row)


@router.post("/payments/{payment_id}/confirm")
def confirm(
    db: Db, user: Superuser, payment_id: uuid.UUID, body: TestCodeIn
) -> dict[str, Any]:
    return _out(testing.confirm(db, actor=user, payment_id=payment_id, code=body.code))


@router.post("/payments/{payment_id}/check")
def check(db: Db, user: Superuser, payment_id: uuid.UUID) -> dict[str, Any]:
    return _out(testing.check(db, actor=user, payment_id=payment_id))


@router.post("/payments/{payment_id}/refund")
def refund(db: Db, user: Superuser, payment_id: uuid.UUID) -> dict[str, Any]:
    return _out(testing.refund(db, actor=user, payment_id=payment_id, now=utcnow()))


@router.post("/cards")
def bind_card(db: Db, user: Superuser, body: TestCardIn) -> dict[str, Any]:
    """Multicard's page to add a test card on; it is read back once added."""
    card, form_url = testing.start_card_binding(
        db, actor=user, phone=body.phone, card_type=body.card_type, now=utcnow()
    )
    return {"id": str(card.id), "form_url": form_url}


@router.delete("/cards/{card_id}")
def remove_card(db: Db, user: Superuser, card_id: uuid.UUID) -> dict[str, Any]:
    """Forget a test card; Multicard voids its token too."""
    testing.remove_test_card(db, actor=user, card_id=card_id, now=utcnow())
    return {"ok": True}
