"""Facebook on a customer's card: taking it away whole, and the leads' verdicts
the nights left unsent.

Disconnecting is the Owner's alone and asks for the address typed back.
Reading and sending the verdicts is for Support, Finance and Owner.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ADMIN_ROLES, Role
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.schemas import (
    FacebookForgottenOut,
    FacebookHoldingsOut,
    SignalBookOut,
    SignalsSentOut,
)
from app.modules.backoffice.selectors.card import person
from app.modules.backoffice.selectors.signals import book_out, signal_book
from app.modules.backoffice.services.facebook import forget_facebook
from app.modules.backoffice.services.signals import send_unsent_signals
from app.modules.integrations.services.forget import meta_holdings

router = APIRouter(prefix="/customers/{customer_id}")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Owner = Annotated[User, Depends(staff_required(Role.OWNER))]
Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class ForgetIn(BaseModel):
    email: str = Field(description="The customer's address, typed back.")
    reason: Reason = Field(description="Why - it goes to the journal.")


class SendIn(BaseModel):
    reason: Reason = Field(description="Why - it goes to the journal.")


def _customer(db: Db, customer_id: uuid.UUID) -> User:
    customer = person(db, customer_id=customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return customer


@router.get("/facebook", responses={200: {"model": FacebookHoldingsOut}})
def facebook_holdings(customer_id: uuid.UUID, db: Db, actor: Owner) -> dict[str, Any]:
    """What disconnecting would take away, counted now."""
    return meta_holdings(db, owner=_customer(db, customer_id)).as_detail()


@router.post("/facebook/forget", responses={200: {"model": FacebookForgottenOut}})
def facebook_forget(
    customer_id: uuid.UUID, body: ForgetIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """Everything Meta brought, gone from our side; nothing is asked of Meta.

    The subscription, its extra pages and the bought seats stay; the setup is
    asked again at the next Meta login.
    """
    customer = _customer(db, customer_id)
    done = forget_facebook(
        db,
        customer=customer,
        actor=actor,
        typed_email=body.email,
        reason=body.reason,
    )
    db.commit()
    held = done.holdings
    return {
        "message": f"Facebook uzildi: {held.pages} ta sahifa, {held.ad_accounts} ta "
        f"kabinet, {held.leads} ta lid o'chirildi. Obuna saqlandi.",
        "rows": done.rows,
        "kept_business": done.kept_business,
    }


@router.get("/signals", responses={200: {"model": SignalBookOut}})
def signals(customer_id: uuid.UUID, db: Db, actor: Admin) -> dict[str, Any]:
    """The last 30 finished days of verdicts, as the night sends them."""
    return book_out(signal_book(db, owner=_customer(db, customer_id), now=utcnow()))


@router.post("/signals/send", responses={200: {"model": SignalsSentOut}})
def signals_send(
    customer_id: uuid.UUID, body: SendIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Send every finished day still unsent, now, the night's way."""
    customer = _customer(db, customer_id)
    result = send_unsent_signals(
        db, customer=customer, actor=actor, reason=body.reason, now=utcnow()
    )
    db.commit()
    return {"message": result.message, "sent": result.sent, "waiting": result.waiting}
