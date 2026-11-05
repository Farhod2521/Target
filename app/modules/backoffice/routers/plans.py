"""The plans, as JSON. Support, Finance and Owner read; the superuser alone writes.

A plan is read live by every subscription on it: limits and pages change for
them at once, the price and the period from their next bill. The trial runs
on the default plan's limits. A plan's code is what the cabinet and the site
know it by, so it is set at creation and never edited. Prices are whole so'm;
the AI spend limit is in the AI provider's cents (``llm_currency``). A limit
of 0 is no limit. A plan off sale (``is_active`` false) is neither bought nor
renewed, also by those already on it.
"""

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Db
from app.common.config import settings
from app.common.exceptions import InputRefused
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import ADMIN_ROLES
from app.modules.backoffice.permissions import staff_required, superuser_required
from app.modules.backoffice.schemas import (
    CreatedOut,
    MessageOut,
    OfficePlanOut,
    OfficePlansOut,
)
from app.modules.backoffice.selectors.plans import (
    PlanRow,
    live_on,
    plan_by_id,
    plan_is_used,
    plan_rows,
)
from app.modules.billing.constants import DEFAULT_PLAN_CODE
from app.modules.billing.models import Plan

router = APIRouter(prefix="/plans")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Superuser = Annotated[User, Depends(superuser_required)]

CODE_SHAPE = re.compile(r"[a-z0-9_]{1,32}")
SMALL = 32767
MONEY = 10**12


class PlanFormIn(BaseModel):
    """One plan. Its code is set at creation and never edited."""

    name: str = Field(max_length=64)
    tagline: str = Field("", max_length=80)
    features: str = Field(
        "",
        max_length=4000,
        description="One line each; `#` starts a heading, `*` a highlight.",
    )
    price: int = Field(ge=0, le=MONEY, description="Whole so'm; 0 is never sold.")
    period_days: int = Field(ge=1, le=366)
    max_adsets: int = Field(0, ge=0, le=SMALL, description="Shown only; 0 is none.")
    daily_chat_requests: int = Field(0, ge=0, le=SMALL, description="0 is no limit.")
    llm_cost_limit_minor: int = Field(
        0, ge=0, le=MONEY, description="A month, in `llm_currency` cents; 0 is none."
    )
    included_pages: int = Field(1, ge=1, le=1000)
    included_google_accounts: int = Field(0, ge=0, le=1000)
    extra_page_price: int = Field(0, ge=0, le=MONEY, description="0 is not sold.")
    crm_seat_price: int = Field(0, ge=0, le=MONEY, description="0 is not sold.")
    is_one_time: bool = False
    is_active: bool = True
    sort_order: int = Field(0, ge=-SMALL, le=SMALL)


class NewPlanFormIn(PlanFormIn):
    code: str = Field(max_length=32, description="Latin letters, digits, `_`.")


def _columns(body: PlanFormIn) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise InputRefused({"name": "Nomini yozing."})
    return body.model_dump(exclude={"code"}) | {
        "name": name,
        "tagline": body.tagline.strip(),
        "features": "\n".join(
            line.rstrip() for line in body.features.strip().splitlines()
        ),
    }


def _new_code(db: Db, raw: str) -> str:
    code = raw.strip().lower()
    if not CODE_SHAPE.fullmatch(code):
        raise InputRefused(
            {"code": "Kod lotin harflari, raqam va «_» dan iborat bo'lsin."}
        )
    if db.scalar(select(Plan.id).where(Plan.code == code)) is not None:
        raise InputRefused({"code": "Bu kod allaqachon bor."})
    return code


def _plan(db: Db, plan_id: uuid.UUID) -> Plan:
    plan = plan_by_id(db, plan_id=plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return plan


def plan_out(row: PlanRow) -> dict[str, Any]:
    plan = row.plan
    return {
        "id": str(plan.id),
        "code": plan.code,
        "name": plan.name,
        "tagline": plan.tagline,
        "features": plan.features,
        "price": plan.price,
        "currency": plan.currency,
        "period_days": plan.period_days,
        "max_adsets": plan.max_adsets,
        "daily_chat_requests": plan.daily_chat_requests,
        "llm_cost_limit_minor": plan.llm_cost_limit_minor,
        "included_pages": plan.included_pages,
        "included_google_accounts": plan.included_google_accounts,
        "extra_page_price": plan.extra_page_price,
        "crm_seat_price": plan.crm_seat_price,
        "is_one_time": plan.is_one_time,
        "is_active": plan.is_active,
        "sort_order": plan.sort_order,
        "is_trial": plan.code == DEFAULT_PLAN_CODE,
        "live": row.live,
        "deletable": row.deletable,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


@router.get("", responses={200: {"model": OfficePlansOut}})
def plans(db: Db, user: Admin) -> dict[str, Any]:
    """Every plan, off-sale ones last, and whether this reader may write."""
    return {
        "rows": [plan_out(row) for row in plan_rows(db)],
        "llm_currency": settings.anthropic_price_currency,
        "can_edit": user.is_superuser,
    }


@router.get("/{plan_id}", responses={200: {"model": OfficePlanOut}})
def plan(plan_id: uuid.UUID, db: Db, user: Admin) -> dict[str, Any]:
    """One plan, for the edit form."""
    row = _plan(db, plan_id)
    return plan_out(PlanRow(row, live_on(db, plan=row), not plan_is_used(db, plan=row)))


@router.post("", responses={200: {"model": CreatedOut}})
def create_plan(body: NewPlanFormIn, db: Db, actor: Superuser) -> dict[str, Any]:
    """Write a new plan; customers are offered it at once when on sale."""
    data = _columns(body) | {"code": _new_code(db, body.code)}
    row = services.create_plan(db, data=data, actor=actor)
    db.commit()
    return {"message": "Tarif yaratildi.", "id": str(row.id)}


@router.put("/{plan_id}", responses={200: {"model": MessageOut}})
def update_plan(
    plan_id: uuid.UUID, body: PlanFormIn, db: Db, actor: Superuser
) -> dict[str, Any]:
    """Rewrite a plan; the subscriptions on it follow at once."""
    services.update_plan(db, plan=_plan(db, plan_id), data=_columns(body), actor=actor)
    db.commit()
    return {"message": "Tarif yangilandi."}


@router.delete("/{plan_id}", responses={200: {"model": MessageOut}})
def delete_plan(plan_id: uuid.UUID, db: Db, actor: Superuser) -> dict[str, Any]:
    """Delete a plan nothing points at; a used one is taken off sale instead."""
    services.delete_plan(db, plan=_plan(db, plan_id), actor=actor)
    db.commit()
    return {"message": "Tarif o'chirildi."}
