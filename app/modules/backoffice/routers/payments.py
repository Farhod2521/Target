"""Bills and entitlements across every account, as JSON.

The Owner and the super admin read it; anybody else is answered 404. Only
the super admin may free a held bill or archive one, and only they see the
archive: for the Owner this screen is read-only.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import Db
from app.common.db import utcnow
from app.common.timezone import localtime
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import STUCK_HOLD_HOURS, Role
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import amounts, choices, person_out
from app.modules.backoffice.routers.customers import invoice_out
from app.modules.backoffice.schemas import (
    MessageOut,
    PaymentInvoicesOut,
    PaymentsSummaryOut,
    PaymentSubscriptionsOut,
)
from app.modules.backoffice.selectors.days import days_left
from app.modules.backoffice.selectors.payments import (
    ARCHIVE_STATE,
    ARCHIVED,
    INVOICE_STATES,
    SUBSCRIPTION_STATES,
    InvoiceRow,
    business_names,
    invoice_page,
    running_out,
    settled_owners,
    stuck_holds,
    subscription_page,
    totals,
)
from app.modules.billing.constants import (
    SUBSCRIPTION_STATUS_LABELS,
    InvoiceStatus,
    SubscriptionStatus,
    TransactionState,
)
from app.modules.billing.models import Invoice, PaymentTransaction, Subscription
from app.modules.billing.services import can_refund, wholly_revocable

router = APIRouter(prefix="/payments")
Owner = Annotated[User, Depends(staff_required(Role.OWNER))]

Q_FIELD = Query("", description="Invoice number, e-mail, name or phone.")
OFFSET = Query(0, ge=0)


class ReasonIn(BaseModel):
    reason: str = Field(
        min_length=1, max_length=500, description="Why - it goes to the journal."
    )


def _hold_out(
    attempt: PaymentTransaction, names: dict[uuid.UUID, str]
) -> dict[str, Any]:
    invoice = attempt.invoice
    return {
        "id": str(attempt.id),
        "number": invoice.number,
        "customer": person_out(attempt.owner),
        "email": attempt.owner.email if attempt.owner else invoice.former_email,
        "business": names.get(attempt.owner_id, "") if attempt.owner_id else "",
        "plan": invoice.plan.name if invoice.plan else "",
        "provider": attempt.provider,
        "amount_minor": attempt.amount_minor,
        "currency": attempt.currency,
        "created_at": attempt.created_at,
    }


def _subscription_state(row: Subscription, settled: frozenset[uuid.UUID]) -> str:
    """The list's one word: a blocked account outranks everything, a trial owes
    nothing yet, and a priced plan nobody ever paid for is the row to chase."""
    if not row.owner.is_active:
        return "blocked"
    if row.status == SubscriptionStatus.TRIAL:
        return "trial"
    return "active" if row.plan.price == 0 or row.owner_id in settled else "unpaid"


def _subscriptions_out(db: Db, rows: Iterable[Subscription]) -> list[dict[str, Any]]:
    rows = list(rows)
    settled = settled_owners(db, (row.owner_id for row in rows))
    now = localtime()
    return [_subscription_out(row, settled, now) for row in rows]


def _subscription_out(
    row: Subscription, settled: frozenset[uuid.UUID], now: datetime
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "customer": person_out(row.owner),
        "plan": {"code": row.plan.code, "name": row.plan.name},
        "status": row.status,
        "status_label": str(
            SUBSCRIPTION_STATUS_LABELS.get(SubscriptionStatus(row.status), row.status)
        ),
        "state": _subscription_state(row, settled),
        "days_left": days_left(expires_at=row.expires_at, now=now),
        "activated_by": person_out(row.activated_by),
        "expires_at": row.expires_at,
    }


def _invoice_row_out(row: InvoiceRow) -> dict[str, Any]:
    invoice, attempt = row.invoice, row.attempt
    return {
        **invoice_out(invoice),
        "id": str(invoice.id),
        "customer": person_out(invoice.owner),
        "email": invoice.owner.email if invoice.owner else invoice.former_email,
        "archive": (
            {
                "at": invoice.archived_at,
                "by": person_out(invoice.archived_by),
                "reason": invoice.archive_reason,
            }
            if invoice.archived_at is not None
            else None
        ),
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
        "refundable": (
            attempt is not None
            and attempt.state == TransactionState.PERFORMED
            and invoice.status == InvoiceStatus.PAID
            and wholly_revocable(invoice)
            and can_refund(attempt.provider)
        ),
    }


@router.get("/summary", responses={200: {"model": PaymentsSummaryOut}})
def summary(db: Db, user: Owner) -> dict[str, Any]:
    """The figures above the list, the held bills and what runs out soon."""
    now = localtime()
    found = totals(db, now=now)
    holds = stuck_holds(db, now=now)
    names = business_names(
        db, (attempt.owner_id for attempt in holds if attempt.owner_id)
    )
    return {
        "totals": {
            "earned": amounts(found.earned),
            "earned_count": found.earned_count,
            "earned_before": amounts(found.earned_before),
            "unpaid": found.unpaid,
            "unpaid_sums": amounts(found.unpaid_sums),
            "stuck": found.stuck,
            "stuck_sums": amounts(found.stuck_sums),
            "stuck_after_hours": STUCK_HOLD_HOURS,
            "refunded": found.refunded,
            "refunded_sums": amounts(found.refunded_sums),
        },
        "holds": [_hold_out(attempt, names) for attempt in holds],
        "running_out": _subscriptions_out(db, running_out(db, now=now)),
    }


@router.get("/invoices", responses={200: {"model": PaymentInvoicesOut}})
def invoices(
    db: Db,
    user: Owner,
    q: str = Q_FIELD,
    state: str = Query("", description="A chip from `states`."),
    offset: int = OFFSET,
) -> dict[str, Any]:
    """Every bill on the books, newest first, 50 at a time. The archive is a
    chip of its own, for the super admin alone."""
    if state == ARCHIVED and not user.is_superuser:
        state = ""
    page = invoice_page(db, state=state, term=q.strip(), offset=offset)
    counts = page.counts
    if not user.is_superuser:
        counts = {key: n for key, n in counts.items() if key != ARCHIVED}
    return {
        "rows": [_invoice_row_out(row) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "states": choices(
            (*INVOICE_STATES, ARCHIVE_STATE) if user.is_superuser else INVOICE_STATES
        ),
        "counts": counts,
    }


@router.post("/invoices/{invoice_id}/archive", responses={200: {"model": MessageOut}})
def archive_invoice(
    invoice_id: uuid.UUID, body: ReasonIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """Take a bill off the books; it stays in the archive. Superuser only.
    Nothing the customer holds changes."""
    if not actor.is_superuser:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    invoice = db.get(Invoice, invoice_id, with_for_update=True)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    services.archive_invoice(
        db, invoice=invoice, actor=actor, reason=body.reason, now=utcnow()
    )
    db.commit()
    return {"message": "Hisob arxivga olindi."}


@router.post("/invoices/{invoice_id}/refund", responses={200: {"model": MessageOut}})
def refund_invoice(
    invoice_id: uuid.UUID, body: ReasonIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """Send a paid bill's money back to the card, and take back the days it
    gave. Superuser only, and only for a provider that can be asked from here
    (Rahmat); the provider says yes before anything here changes."""
    if not actor.is_superuser:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    services.refund_invoice(
        db, invoice=invoice, actor=actor, reason=body.reason, now=utcnow()
    )
    db.commit()
    return {"message": "Pul kartaga qaytarildi."}


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
        "rows": _subscriptions_out(db, page.rows),
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "states": choices(SUBSCRIPTION_STATES),
        "counts": page.counts,
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
