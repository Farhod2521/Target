"""Promo codes, and the queue of requests waiting for an answer, as JSON.

Every admin role reads the screen and answers requests: what is given is
whatever the code already says, so a yes is customer care. Writing a code
decides what the next hundred requests are worth, so the catalogue's
writes are Finance's and the Owner's.

Money is typed the way it is written: a fixed discount and the smallest
bill arrive in whole units of the billing currency and are stored in minor
units. A box that asked for tiyin would be a hundredfold mistake.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Db
from app.common.config import settings
from app.common.dates import office_zone
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.common.money import decimal_places, to_major, to_minor
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import ADMIN_ROLES, MONEY_ROLES
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import choices, person_out
from app.modules.backoffice.schemas import (
    CreatedOut,
    MessageOut,
    PromoCodeOut,
    PromoOut,
)
from app.modules.backoffice.selectors.promo import (
    ANSWERED_TAB,
    STATUS_LABELS,
    CodeRow,
    RequestRow,
    catalogue,
    code_by_id,
    fill_percent,
    request_by_id,
    requests,
    status_of,
)
from app.modules.billing.constants import (
    PROMO_DISCOUNT_KIND_LABELS,
    PROMO_KIND_LABELS,
    PROMO_SCOPE_LABELS,
    REDEMPTION_STATUS_LABELS,
    PromoDiscountKind,
    PromoKind,
    PromoScope,
)
from app.modules.billing.models import Plan, PromoCode, PromoRedemption
from app.modules.billing.models.promo_code import normalise
from app.modules.billing.selectors import every_plan
from app.modules.billing.selectors.promo import times_used

router = APIRouter(prefix="/promo")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Money = Annotated[User, Depends(staff_required(*MONEY_ROLES))]

# The widest percent a code may take off. A hundred would leave nothing to
# pay, and a bill of nothing has no provider path.
MAX_PERCENT = 99
SMALL = 32767
LARGE = 2147483647


class CodeIn(BaseModel):
    """One offer. Only the kind's own fields are written; the others are
    ignored, so a crafted press cannot carry another kind's figures in."""

    code: str = Field(min_length=1, max_length=32)
    description: str = Field("", max_length=255)
    is_active: bool = True
    starts_at: datetime | None = Field(None, description="Empty: works at once.")
    expires_at: datetime | None = None
    max_uses: int = Field(0, ge=0, le=LARGE, description="0 = no ceiling.")
    max_uses_per_user: int = Field(1, ge=0, le=SMALL, description="0 = no ceiling.")
    note: str = Field("", max_length=5000)
    grant_days: int = Field(0, ge=0, le=SMALL, description="Kind `plan`.")
    plan: str = Field("", description="Kind `plan`: a plan code, or empty.")
    grant_pages: int = Field(0, ge=0, le=SMALL, description="Kind `slots`.")
    needs_approval: bool = Field(False, description="Kinds `plan` and `slots`.")
    discount_kind: PromoDiscountKind | None = Field(
        None, description="Kind `discount`: `percent` or `amount`."
    )
    discount_value: int = Field(
        0, ge=0, le=10**12, description="A percent 1-99, or whole units."
    )
    scope: PromoScope = PromoScope.BOTH
    min_amount: int = Field(0, ge=0, le=10**12, description="Whole units; 0 = any.")


class NewCodeIn(CodeIn):
    kind: PromoKind


class RefuseIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _aware(value: datetime | None) -> datetime | None:
    """A time typed without a zone is the office's, as a picker writes it."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=office_zone())


def _minor(whole: int) -> int:
    return int(to_minor(amount=str(whole), currency=settings.billing_currency))


def _whole(minor: int) -> int:
    places = decimal_places(settings.billing_currency)
    return int(to_major(amount_minor=minor, places=places) or 0)


def _columns(
    db: Db, *, body: CodeIn, kind: PromoKind, code_id: uuid.UUID | None
) -> dict[str, Any]:
    """The columns this kind writes, or every problem at once.

    A code that grants is bounded by a deadline and a ceiling of its own,
    because nothing else bounds it; a discount needs a figure and takes no
    approval; the end comes after the start.
    """
    problems: dict[str, str] = {}
    code = normalise(body.code)
    clash = select(PromoCode.id).where(PromoCode.code == code)
    if code_id is not None:
        clash = clash.where(PromoCode.id != code_id)
    if not code:
        problems["code"] = "Kodni yozing."
    elif db.scalar(clash) is not None:
        problems["code"] = "Bu kod allaqachon bor."
    starts_at, expires_at = _aware(body.starts_at), _aware(body.expires_at)
    data: dict[str, Any] = {
        "code": code,
        "description": body.description.strip(),
        "starts_at": starts_at,
        "expires_at": expires_at,
        "max_uses": body.max_uses,
        "max_uses_per_user": body.max_uses_per_user,
        "is_active": body.is_active,
        "note": body.note.strip(),
    }
    if kind == PromoKind.DISCOUNT:
        data |= _discount(body, problems)
    else:
        if not expires_at:
            problems["expires_at"] = (
                "Nimadir beradigan kod uchun tugash vaqti majburiy."
            )
        if not body.max_uses:
            problems["max_uses"] = "Nimadir beradigan kod uchun umumiy limit majburiy."
        data["needs_approval"] = body.needs_approval
    if kind == PromoKind.PLAN:
        plan = (
            db.scalar(select(Plan).where(Plan.code == body.plan)) if body.plan else None
        )
        if body.plan and plan is None:
            problems["plan"] = "Tarifni tanlang."
        elif not body.grant_days and plan is None:
            problems["grant_days"] = "Tarif kodi kun yoki tarif berishi kerak."
        data |= {"grant_days": body.grant_days, "plan_id": plan.id if plan else None}
    if kind == PromoKind.SLOTS:
        if not body.grant_pages:
            problems["grant_pages"] = "O'rin kodi sahifa berishi kerak."
        data["grant_pages"] = body.grant_pages
    if starts_at and expires_at and expires_at <= starts_at:
        problems["expires_at"] = (
            "Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak."
        )
    if problems:
        raise InputRefused(problems)
    return data


def _discount(body: CodeIn, problems: dict[str, str]) -> dict[str, Any]:
    if body.needs_approval:
        problems["needs_approval"] = (
            "Chegirma kodi darhol qo'llanadi, tasdiq kutib bo'lmaydi."
        )
    is_percent = body.discount_kind == PromoDiscountKind.PERCENT
    if body.discount_kind not in (PromoDiscountKind.PERCENT, PromoDiscountKind.AMOUNT):
        problems["discount_kind"] = "Chegirma turini tanlang."
    elif not body.discount_value:
        problems["discount_value"] = "Chegirma kodi chegirma qiymatini talab qiladi."
    elif is_percent and body.discount_value > MAX_PERCENT:
        problems["discount_value"] = "Foiz 1 dan 99 gacha bo'lishi kerak."
    return {
        "discount_kind": str(body.discount_kind or ""),
        "discount_value": (
            body.discount_value if is_percent else _minor(body.discount_value)
        ),
        "scope": str(body.scope),
        "min_amount_minor": _minor(body.min_amount),
    }


def _label(labels: Mapping[Any, str], value: str) -> str:
    return str(labels.get(value, value))


def code_out(row: CodeRow) -> dict[str, Any]:
    code = row.code
    return {
        "id": str(code.id),
        "code": code.code,
        "kind": code.kind,
        "kind_label": _label(PROMO_KIND_LABELS, code.kind),
        "description": code.description,
        "is_active": code.is_active,
        "status": row.status,
        "status_label": STATUS_LABELS[row.status],
        "used": row.used,
        "percent": row.percent,
        "starts_at": code.starts_at,
        "expires_at": code.expires_at,
        "max_uses": code.max_uses,
        "max_uses_per_user": code.max_uses_per_user,
        "note": code.note,
        "grant_days": code.grant_days,
        "plan": (
            {"code": code.plan.code, "name": code.plan.name} if code.plan else None
        ),
        "grant_pages": code.grant_pages,
        "needs_approval": code.needs_approval,
        "discount_kind": code.discount_kind,
        "discount_value": (
            _whole(code.discount_value)
            if code.discount_kind == PromoDiscountKind.AMOUNT
            else code.discount_value
        ),
        "scope": code.scope,
        "min_amount": _whole(code.min_amount_minor),
        "created_at": code.created_at,
    }


def request_out(row: RequestRow) -> dict[str, Any]:
    redemption = row.redemption
    promo = redemption.promo
    return {
        "id": str(redemption.id),
        "customer": person_out(redemption.owner),
        "code": promo.code,
        "kind": promo.kind,
        "kind_label": _label(PROMO_KIND_LABELS, promo.kind),
        "description": promo.description,
        "offers": {
            "days": promo.grant_days,
            "pages": promo.grant_pages,
            "plan": promo.plan.name if promo.plan is not None else "",
        },
        "redeemed_at": redemption.redeemed_at,
        "refused_before": row.refused_before,
        "status": redemption.status,
        "status_label": _label(REDEMPTION_STATUS_LABELS, redemption.status),
        "decided_at": redemption.decided_at,
        "decided_by": person_out(redemption.decided_by),
        "decision_note": redemption.decision_note,
    }


def _request(db: Db, request_id: uuid.UUID) -> PromoRedemption:
    redemption = request_by_id(db, request_id=request_id)
    if redemption is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return redemption


def _code(db: Db, code_id: uuid.UUID) -> PromoCode:
    code = code_by_id(db, code_id=code_id)
    if code is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return code


@router.get("", responses={200: {"model": PromoOut}})
def promo(
    db: Db,
    user: Admin,
    tab: str = Query("", description="`answered` for answers given; else the queue."),
    q: str = Query("", max_length=100, description="A name, an email, or a code."),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """One page of the requests, and the whole catalogue beside them."""
    answered = tab == ANSWERED_TAB
    page = requests(db, answered=answered, term=q.strip(), offset=offset)
    shelf = catalogue(db, now=utcnow())
    return {
        "tab": ANSWERED_TAB if answered else "",
        "requests": [request_out(row) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "current": [code_out(row) for row in shelf.current],
        "finished": [code_out(row) for row in shelf.finished],
        "currency": settings.billing_currency,
        "kinds": choices([(str(k), str(v)) for k, v in PROMO_KIND_LABELS.items()]),
        "discount_kinds": choices(
            [
                (str(k), str(v))
                for k, v in PROMO_DISCOUNT_KIND_LABELS.items()
                if k != PromoDiscountKind.NONE
            ]
        ),
        "scopes": choices([(str(k), str(v)) for k, v in PROMO_SCOPE_LABELS.items()]),
        "plans": choices([(p.code, p.name) for p in every_plan(db)]),
    }


@router.get("/codes/{code_id}", responses={200: {"model": PromoCodeOut}})
def promo_code(code_id: uuid.UUID, db: Db, user: Admin) -> dict[str, Any]:
    """One catalogue row, for the edit form."""
    code = _code(db, code_id)
    used = times_used(db, promo=code)
    return code_out(
        CodeRow(
            code=code,
            used=used,
            percent=fill_percent(used, code.max_uses),
            status=status_of(code=code, used=used, now=utcnow()),
        )
    )


@router.post("/codes", responses={200: {"model": CreatedOut}})
def create_code(body: NewCodeIn, db: Db, actor: Money) -> dict[str, Any]:
    """Write a new offer of the kind named."""
    data = _columns(db, body=body, kind=body.kind, code_id=None)
    code = services.create_code(db, kind=body.kind, data=data, actor=actor)
    db.commit()
    return {"message": "Kod yaratildi.", "id": str(code.id)}


@router.put("/codes/{code_id}", responses={200: {"model": MessageOut}})
def update_code(
    code_id: uuid.UUID, body: CodeIn, db: Db, actor: Money
) -> dict[str, Any]:
    """Rewrite one offer's figures. The kind is the row's, never the press's."""
    code = _code(db, code_id)
    data = _columns(db, body=body, kind=PromoKind(code.kind), code_id=code.id)
    services.update_code(db, code=code, data=data, actor=actor)
    db.commit()
    return {"message": "Kod yangilandi."}


@router.delete("/codes/{code_id}", responses={200: {"model": MessageOut}})
def delete_code(code_id: uuid.UUID, db: Db, actor: Money) -> dict[str, Any]:
    """Delete an offer nobody has taken; a used one is switched off instead."""
    services.delete_code(db, code=_code(db, code_id), actor=actor)
    db.commit()
    return {"message": "Kod o'chirildi."}


@router.post("/requests/{request_id}/approve", responses={200: {"model": MessageOut}})
def approve_request(request_id: uuid.UUID, db: Db, actor: Admin) -> dict[str, Any]:
    """Hand over what the request asked for."""
    services.approve_promo(
        db, redemption=_request(db, request_id), actor=actor, now=utcnow()
    )
    db.commit()
    return {"message": "Promo tasdiqlandi."}


@router.post("/requests/{request_id}/refuse", responses={200: {"model": MessageOut}})
def refuse_request(
    request_id: uuid.UUID, body: RefuseIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Refuse a request, keeping the sentence that says why."""
    services.refuse_promo(
        db,
        redemption=_request(db, request_id),
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    db.commit()
    return {"message": "Promo rad etildi."}
