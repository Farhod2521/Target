"""The writes on a customer's card, as JSON.

Each answers the sentence that says what happened; a refusal is the
DomainError body. The card is re-read afterwards: every write here moves
something the rest of the card also shows.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Db
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import ADMIN_ROLES, MONEY_ROLES, Role
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.schemas import DeletedOut, MessageOut
from app.modules.backoffice.selectors.card import person
from app.modules.billing.constants import MAX_GRANT_DAYS, MAX_SLOT_CHANGE, ManualMethod
from app.modules.billing.models import Plan
from app.modules.integrations.models import PageAccount
from app.modules.integrations.selectors.connection import pages
from app.modules.referrals.constants import PayoutMethod, ReferralMode

router = APIRouter(prefix="/customers/{customer_id}")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Money = Annotated[User, Depends(staff_required(*MONEY_ROLES))]
Owner = Annotated[User, Depends(staff_required(Role.OWNER))]


class ReasonIn(BaseModel):
    reason: str = Field(
        min_length=1, max_length=500, description="Why - it goes to the journal."
    )


class PaidIn(ReasonIn):
    """Did the customer pay for this? No by default; yes needs the amount and
    how it came, and becomes a paid bill the dashboard counts."""

    paid: bool = False
    amount: Decimal | None = Field(
        None, gt=0, max_digits=16, decimal_places=2, description="Whole units."
    )
    method: ManualMethod | None = None
    pay_reference: str = Field("", max_length=128)

    def payment(self) -> services.Payment | None:
        if not self.paid:
            return None
        problems = {}
        if self.amount is None:
            problems["amount"] = "To'lov summasini kiriting."
        if self.method is None:
            problems["method"] = "To'lov usulini tanlang."
        if problems or self.amount is None or self.method is None:
            raise InputRefused(problems)
        return services.Payment(
            amount=self.amount, method=self.method, reference=self.pay_reference.strip()
        )


class PlanIn(PaidIn):
    plan: str = Field(description="A plan code; withdrawn plans may be given too.")


class DaysIn(PaidIn):
    days: int = Field(ge=1, le=MAX_GRANT_DAYS)


class SlotsIn(PaidIn):
    pages: int = Field(ge=1, le=MAX_SLOT_CHANGE)
    take: bool = Field(False, description="Take room back instead of giving it.")


class PaymentIn(ReasonIn):
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    method: ManualMethod
    pay_reference: str = Field("", max_length=128)


class ReferralIn(ReasonIn):
    mode: ReferralMode


class MovePageIn(ReasonIn):
    target: uuid.UUID = Field(description="The page that takes this one's slot.")


class PageAccountIn(ReasonIn):
    current: str = Field("", description="The pair's ad account id; empty if none.")
    target: str = Field(min_length=1, max_length=64)


class RemovePairIn(ReasonIn):
    account: str = Field(min_length=1, max_length=64)


class PasswordIn(ReasonIn):
    new_password1: str = Field(min_length=1, max_length=128)
    new_password2: str = Field(min_length=1, max_length=128)


class DeleteIn(BaseModel):
    email: str = Field(description="The customer's address, typed back.")


class PayoutIn(ReasonIn):
    amount: Decimal = Field(ge=1, max_digits=16, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    method: PayoutMethod
    pay_reference: str = Field("", max_length=128)


def _customer(db: Db, customer_id: uuid.UUID) -> User:
    customer = person(db, customer_id=customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return customer


def _page(db: Db, *, customer: User, page_id: uuid.UUID) -> PageAccount:
    page = next((p for p in pages(db, owner=customer) if p.id == page_id), None)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return page


def _done(db: Db, message: str) -> dict[str, Any]:
    db.commit()
    return {"message": message}


@router.post("/plan", responses={200: {"model": MessageOut}})
def give_plan(
    customer_id: uuid.UUID, body: PlanIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Put the account on a plan, with the plan's whole period."""
    customer = _customer(db, customer_id)
    plan = db.scalar(select(Plan).where(Plan.code == body.plan))
    if plan is None:
        raise InputRefused({"plan": "Tarifni tanlang."})
    services.give_plan(
        db,
        customer=customer,
        plan=plan,
        payment=body.payment(),
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "Tarif berildi.")


@router.post("/days", responses={200: {"model": MessageOut}})
def give_days(
    customer_id: uuid.UUID, body: DaysIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Add days to the entitlement; a lapsed one is reopened on its last plan."""
    customer = _customer(db, customer_id)
    services.add_days(
        db,
        customer=customer,
        days=body.days,
        payment=body.payment(),
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "Muddat uzaytirildi.")


@router.post("/slots", responses={200: {"model": MessageOut}})
def change_slots(
    customer_id: uuid.UUID, body: SlotsIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Give room for more pages, or take room back (`take`)."""
    customer = _customer(db, customer_id)
    if body.take:
        if body.paid:
            raise InputRefused({"paid": "Olingan o'rin uchun to'lov yozilmaydi."})
        services.take_slots(
            db,
            customer=customer,
            pages=body.pages,
            actor=actor,
            reason=body.reason,
            now=utcnow(),
        )
    else:
        services.add_slots(
            db,
            customer=customer,
            pages=body.pages,
            payment=body.payment(),
            actor=actor,
            reason=body.reason,
            now=utcnow(),
        )
    return _done(db, "O'rinlar yangilandi.")


@router.post("/payment", responses={200: {"model": MessageOut}})
def record_payment(
    customer_id: uuid.UUID, body: PaymentIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Write down money for access the account already has."""
    customer = _customer(db, customer_id)
    services.take_payment(
        db,
        customer=customer,
        payment=services.Payment(
            amount=body.amount, method=body.method, reference=body.pay_reference.strip()
        ),
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "To'lov qayd etildi.")


@router.post("/referral", responses={200: {"model": MessageOut}})
def change_referral(
    customer_id: uuid.UUID, body: ReferralIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Open, close, or hand back to the rule this account's invitation link."""
    customer = _customer(db, customer_id)
    services.set_referral(
        db,
        customer=customer,
        mode=body.mode,
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "Referal yangilandi.")


@router.post("/receipts", responses={200: {"model": MessageOut}})
def attach_receipts(
    customer_id: uuid.UUID, body: ReasonIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Attach the paid bills a deleted account on this address left. Grants nothing."""
    customer = _customer(db, customer_id)
    attached = services.attach_old_receipts(
        db, customer=customer, actor=actor, reason=body.reason
    )
    return _done(db, f"{attached} ta eski chek ulandi.")


@router.post("/payout", responses={200: {"model": MessageOut}})
def record_payout(
    customer_id: uuid.UUID, body: PayoutIn, db: Db, actor: Money
) -> dict[str, Any]:
    """Record that this Hamyon paid out, after the money already moved."""
    customer = _customer(db, customer_id)
    currency = body.currency.upper()
    if currency not in services.payout_currencies(db, customer=customer):
        raise InputRefused({"currency": "Bu valyutada Hamyon yo'q."})
    services.record_withdrawal(
        db,
        customer=customer,
        amount=body.amount,
        currency=currency,
        method=body.method,
        pay_reference=body.pay_reference.strip(),
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "To'lov qayd etildi.")


@router.post("/pages/{page_id}/add", responses={200: {"model": MessageOut}})
def add_page(
    customer_id: uuid.UUID, page_id: uuid.UUID, body: PaidIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """One more slot past the plan, and this page switched on in it. Owner only."""
    customer = _customer(db, customer_id)
    page = _page(db, customer=customer, page_id=page_id)
    services.add_page(
        db,
        customer=customer,
        page=page,
        payment=body.payment(),
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "Sahifa obunaga qo'shildi.")


@router.post("/pages/{page_id}/move", responses={200: {"model": MessageOut}})
def move_page(
    customer_id: uuid.UUID, page_id: uuid.UUID, body: MovePageIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Hand this page's slot to another of the account's pages."""
    customer = _customer(db, customer_id)
    source = _page(db, customer=customer, page_id=page_id)
    target = _page(db, customer=customer, page_id=body.target)
    services.move_page(
        db,
        customer=customer,
        source=source,
        target=target,
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "Sahifa o'tkazildi.")


@router.post("/pages/{page_id}/account", responses={200: {"model": MessageOut}})
def change_page_account(
    customer_id: uuid.UUID,
    page_id: uuid.UUID,
    body: PageAccountIn,
    db: Db,
    actor: Admin,
) -> dict[str, Any]:
    """Move one of the page's pairs to another of the account's ad accounts."""
    customer = _customer(db, customer_id)
    page = _page(db, customer=customer, page_id=page_id)
    services.change_page_account(
        db,
        customer=customer,
        page=page,
        current=body.current,
        target=body.target,
        actor=actor,
        reason=body.reason,
    )
    return _done(db, "Reklama akkaunti almashtirildi.")


@router.post("/pages/{page_id}/remove-pair", responses={200: {"model": MessageOut}})
def remove_page_pair(
    customer_id: uuid.UUID,
    page_id: uuid.UUID,
    body: RemovePairIn,
    db: Db,
    actor: Admin,
) -> dict[str, Any]:
    """Take one of the page's pairs away; the page and the account stay."""
    customer = _customer(db, customer_id)
    page = _page(db, customer=customer, page_id=page_id)
    services.remove_page_account(
        db,
        customer=customer,
        page=page,
        account=body.account,
        actor=actor,
        reason=body.reason,
    )
    return _done(db, "Juftlik o'chirildi.")


@router.post("/password", responses={200: {"model": MessageOut}})
def set_password(
    customer_id: uuid.UUID, body: PasswordIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """Set the customer's password and sign them out everywhere. Superuser only."""
    if not actor.is_superuser:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    customer = _customer(db, customer_id)
    if body.new_password1 != body.new_password2:
        raise InputRefused({"new_password2": "Parollar bir xil emas."})
    services.set_customer_password(
        db,
        customer=customer,
        actor=actor,
        new_password=body.new_password2,
        reason=body.reason,
        now=utcnow(),
    )
    return _done(db, "Parol o'rnatildi. Mijoz hamma qurilmada chiqarildi.")


@router.post("/delete", responses={200: {"model": DeletedOut}})
def delete_customer(
    customer_id: uuid.UUID, body: DeleteIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """Erase the account with everything in it; paid bills stay. Owner only."""
    customer = _customer(db, customer_id)
    report = services.delete_account(
        db, customer=customer, actor=actor, typed_email=body.email
    )
    return {
        "message": f"{report.email} o'chirildi. Saqlangan to'langan cheklar: "
        f"{report.receipts_kept}.",
        "rows": report.rows,
        "receipts_kept": report.receipts_kept,
    }
