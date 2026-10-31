"""Bills and entitlements across every account, as JSON.

The Owner and the super admin read it; anybody else is answered 404. Only
the super admin may free a held bill: for the Owner this screen is read-only.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import Db
from app.common.db import utcnow
from app.common.timezone import localtime
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import Role
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import amounts, choices, person_out
from app.modules.backoffice.routers.customers import invoice_out
from app.modules.backoffice.schemas import (
    MessageOut,
    PaymentInvoicesOut,
    PaymentsSummaryOut,
    PaymentSubscriptionsOut,
)
from app.modules.backoffice.selectors.payments import (
    INVOICE_STATES,
    SUBSCRIPTION_STATES,
    InvoiceRow,
    invoice_page,
    running_out,
    stuck_holds,
    subscription_page,
    totals,
)
from app.modules.billing.constants import (
    SUBSCRIPTION_STATUS_LABELS,
    SubscriptionStatus,
)
from app.modules.billing.models import PaymentTransaction, Subscription

router = APIRouter(prefix="/payments")
Owner = Annotated[User, Depends(staff_required(Role.OWNER))]

Q_FIELD = Query("", description="Invoice number, e-mail, name or phone.")
OFFSET = Query(0, ge=0)


class ReasonIn(BaseModel):
    reason: str = Field(
        min_length=1, max_length=500, description="Why - it goes to the journal."
    )


def _hold_out(attempt: PaymentTransaction) -> dict[str, Any]:
    invoice = attempt.invoice
    return {
        "id": str(attempt.id),
        "number": invoice.number,
        "customer": person_out(attempt.owner),
        "email": attempt.owner.email if attempt.owner else invoice.former_email,
        "provider": attempt.provider,
        "amount_minor": attempt.amount_minor,
        "currency": attempt.currency,
        "created_at": attempt.created_at,
    }


def _subscription_out(row: Subscription) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "customer": person_out(row.owner),
        "plan": {"code": row.plan.code, "name": row.plan.name},
        "status": row.status,
        "status_label": str(
            SUBSCRIPTION_STATUS_LABELS.get(SubscriptionStatus(row.status), row.status)
        ),
        "expires_at": row.expires_at,
    }


def _invoice_row_out(row: InvoiceRow) -> dict[str, Any]:
    invoice, attempt = row.invoice, row.attempt
    return {
        **invoice_out(invoice),
        "id": str(invoice.id),
        "customer": person_out(invoice.owner),
        "email": invoice.owner.email if invoice.owner else invoice.former_email,
        "transaction": (
            {
                "id": str(attempt.id),
                "provider": attempt.provider,
                "external_id": attempt.external_id,
                "state": attempt.state,
            }
            if attempt is not None
            else None
        ),
    }


@router.get("/summary", responses={200: {"model": PaymentsSummaryOut}})
def summary(db: Db, user: Owner) -> dict[str, Any]:
    """The figures above the list, the held bills and what runs out soon."""
    now = localtime()
    found = totals(db, now=now)
    return {
        "totals": {
            "earned": amounts(found.earned),
            "unpaid": found.unpaid,
            "unpaid_sums": amounts(found.unpaid_sums),
            "stuck": found.stuck,
            "refunded": found.refunded,
        },
        "holds": [_hold_out(attempt) for attempt in stuck_holds(db, now=now)],
        "running_out": [_subscription_out(row) for row in running_out(db, now=now)],
    }


@router.get("/invoices", responses={200: {"model": PaymentInvoicesOut}})
def invoices(
    db: Db,
    user: Owner,
    q: str = Q_FIELD,
    state: str = Query("", description="A chip from `states`."),
    offset: int = OFFSET,
) -> dict[str, Any]:
    """Every bill, newest first, 50 at a time."""
    page = invoice_page(db, state=state, term=q.strip(), offset=offset)
    return {
        "rows": [_invoice_row_out(row) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "states": choices(INVOICE_STATES),
    }


@router.get("/subscriptions", responses={200: {"model": PaymentSubscriptionsOut}})
def subscriptions(
    db: Db,
    user: Owner,
    q: str = Query("", description="E-mail, name or phone."),
    state: str = Query("", description="A chip from `states`."),
    offset: int = OFFSET,
) -> dict[str, Any]:
    """Live subscriptions, soonest to end first, 50 at a time."""
    page = subscription_page(
        db, now=localtime(), state=state, term=q.strip(), offset=offset
    )
    return {
        "rows": [_subscription_out(row) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "states": choices(SUBSCRIPTION_STATES),
    }


@router.post("/holds/{attempt_id}/release", responses={200: {"model": MessageOut}})
def release_hold(
    attempt_id: uuid.UUID, body: ReasonIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """Free a bill an abandoned card screen is holding. Superuser only."""
    if not actor.is_superuser:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    attempt = db.get(PaymentTransaction, attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    services.free_hold(
        db, attempt=attempt, actor=actor, reason=body.reason, now=utcnow()
    )
    db.commit()
    return {"message": "Hisob bo'shatildi."}
