"""Hamyon in the office, as JSON: the asks waiting, what went out, the answers.

Support, Finance and Owner read it; only Finance and Owner answer, and only they
are sent the whole card and its holder. Each answer's refusal is the DomainError
body.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import ADMIN_ROLES, MONEY_ROLES
from app.modules.backoffice.permissions import has_role, staff_required
from app.modules.backoffice.routers._out import choices, person_out
from app.modules.backoffice.schemas import (
    MessageOut,
    PayoutHistoryOut,
    PayoutQueueOut,
)
from app.modules.backoffice.selectors.payments import business_names
from app.modules.backoffice.selectors.wallet import (
    PAYOUT_STATES,
    card_number,
    is_overdue,
    payout_by_id,
    payout_page,
    waiting_asks,
)
from app.modules.referrals.constants import PAYOUT_METHOD_LABELS
from app.modules.referrals.models import WithdrawalRequest

router = APIRouter(prefix="/wallet")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Money = Annotated[User, Depends(staff_required(*MONEY_ROLES))]


class ReasonIn(BaseModel):
    reason: str = Field(
        min_length=1, max_length=500, description="Why - the earner reads it."
    )


class PayIn(BaseModel):
    pay_reference: str = Field("", max_length=128)


def _customer(row: WithdrawalRequest, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    person = person_out(row.owner) or {}
    return {**person, "business": names.get(row.owner_id, "")}


def _money(row: WithdrawalRequest) -> dict[str, Any]:
    return {
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "method_label": PAYOUT_METHOD_LABELS.get(row.method, row.method),
        "card_last4": row.card_last4,
    }


def _totals(rows: list[WithdrawalRequest]) -> list[dict[str, Any]]:
    """Two currencies never add."""
    sums: dict[str, int] = {}
    for row in rows:
        sums[row.currency] = sums.get(row.currency, 0) + row.amount_minor
    return [
        {"currency": currency, "amount_minor": minor}
        for currency, minor in sorted(sums.items())
    ]


def _history_row(row: WithdrawalRequest, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    voided = row.voided_at is not None
    return {
        **_money(row),
        "id": str(row.id),
        "customer": _customer(row, names),
        "status": row.status,
        "pay_reference": row.pay_reference,
        "reason": row.void_reason if voided else row.reject_reason,
        "by": person_out(row.voided_by if voided else row.decided_by),
        "at": row.voided_at or row.decided_at or row.created_at,
    }


def _payout(db: Db, payout_id: uuid.UUID) -> WithdrawalRequest:
    row = payout_by_id(db, payout_id=payout_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return row


def _done(db: Db, message: str) -> dict[str, Any]:
    db.commit()
    return {"message": message}


@router.get("/queue", responses={200: {"model": PayoutQueueOut}})
def queue(db: Db, user: Admin) -> dict[str, Any]:
    """Earners waiting for their money, the one waiting longest first."""
    can_act = has_role(db, user, MONEY_ROLES)
    asks = waiting_asks(db)
    names = business_names(db, (ask.owner_id for ask in asks))
    now = utcnow()
    return {
        "can_act": can_act,
        "totals": _totals(asks),
        "rows": [
            {
                **_money(ask),
                "id": str(ask.id),
                "customer": _customer(ask, names),
                "card_number": card_number(ask) if can_act else None,
                "card_holder": ask.card_holder if can_act else None,
                "created_at": ask.created_at,
                "overdue": is_overdue(ask, now=now),
            }
            for ask in asks
        ],
    }


@router.get("/history", responses={200: {"model": PayoutHistoryOut}})
def history(
    db: Db,
    user: Admin,
    state: str = Query("", description="A chip from `states`."),
    q: str = Query("", description="E-mail, name, phone, last four, reference."),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Every answered payout, newest first, 50 at a time."""
    page = payout_page(db, state=state, term=q.strip(), offset=offset)
    names = business_names(db, (row.owner_id for row in page.rows))
    return {
        "rows": [_history_row(row, names) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "states": choices(PAYOUT_STATES),
        "counts": page.counts,
    }


@router.post("/{payout_id}/paid", responses={200: {"model": MessageOut}})
def mark_paid(
    payout_id: uuid.UUID, body: PayIn, db: Db, actor: Money
) -> dict[str, Any]:
    """The money went to the earner's card: close the ask as paid."""
    services.pay_ask(
        db,
        ask=_payout(db, payout_id),
        pay_reference=body.pay_reference,
        actor=actor,
        now=utcnow(),
    )
    return _done(db, "To'lov qayd etildi.")


@router.post("/{payout_id}/reject", responses={200: {"model": MessageOut}})
def turn_down(
    payout_id: uuid.UUID, body: ReasonIn, db: Db, actor: Money
) -> dict[str, Any]:
    """Turn the ask down; the reason is what the earner reads."""
    services.refuse_ask(
        db,
        ask=_payout(db, payout_id),
        reason=body.reason,
        actor=actor,
        now=utcnow(),
    )
    return _done(db, "So'rov rad etildi.")


@router.post("/{payout_id}/void", responses={200: {"model": MessageOut}})
def void_payout(
    payout_id: uuid.UUID, body: ReasonIn, db: Db, actor: Money
) -> dict[str, Any]:
    """Void a mistaken payout record, keeping the sentence that says why."""
    services.void_withdrawal(
        db,
        payout=_payout(db, payout_id),
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "Yozuv bekor qilindi.")
