"""The marketing site's data: the home page, the consult form, the legal pages.

The pages themselves are drawn by the frontend; these answer what Django's
templates were given. ``callbacks`` holds the Meta deletion callback, which
lives at the root and takes a form post.
"""

import logging
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.api.deps import Db, OptionalUser, client_address
from app.common import storage
from app.common.config import settings
from app.common.i18n import get_language
from app.common.throttle import record, spent
from app.modules.public import selectors, services
from app.modules.public.constants import (
    ADVERTISER_POLICY_UPDATED_AT,
    CONSULT_PER_ADDRESS,
    CONSULT_WINDOW_SECONDS,
    DELETION_SLA_DAYS,
    FEATURES,
    LEGAL_UPDATED_AT,
    PROBLEMS,
    QUESTIONS,
    STEPS,
    TARGETING_SAMPLE,
    TESTIMONIAL_MIN_SET,
    TESTIMONIAL_SECONDS_PER_CARD,
    TIER_INCLUDES,
    DeletionRequestSource,
)
from app.modules.public.exceptions import DeletionRequestNotFound, InvalidSignedRequest
from app.modules.public.models import Testimonial
from app.modules.public.schemas import (
    BusinessPrivacyOut,
    ConsultOut,
    DeletionCreatedOut,
    DeletionPageOut,
    DeletionStatusOut,
    HomeOut,
    PrivacyOut,
    TermsOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/public", tags=["public"])
callbacks = APIRouter(tags=["public"])
BUCKET = "consult:address"
MONTH_DAYS = 30


def _region() -> str:
    return settings.profile_defaults["country_code"]


def testimonial_out(row: Testimonial) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "image": storage.url(row.image),
        "video": storage.url(row.video),
        "audio": storage.url(row.audio),
        "text": row.text,
    }


@router.get("/home", responses={200: {"model": HomeOut}})
def home(db: Db, reader: OptionalUser, request: Request) -> dict[str, Any]:
    from app.modules.billing.routers import plan_out, shown_prices
    from app.modules.billing.selectors import (
        display_as_dict,
        featured_plan,
        payments_configured,
        public_plans,
    )
    from core.leads.phone import dial_code, example_national

    plans = public_plans(db, owner=reader)
    testimonials = selectors.active_testimonials(db)
    cards: list[tuple[Testimonial, bool]] = [(row, False) for row in testimonials]
    while testimonials and len(cards) < TESTIMONIAL_MIN_SET:
        cards.extend((row, True) for row in testimonials)
    monthly = [plan for plan in plans if plan.price and plan.period_days >= MONTH_DAYS]
    region = _region()
    return {
        "dial_code": dial_code(region),
        "phone_example": example_national(region),
        "testimonials": [testimonial_out(row) for row in testimonials],
        "testimonial_cards": [
            testimonial_out(row) | {"is_copy": copy} for row, copy in cards
        ],
        "testimonial_loop_seconds": len(cards) * TESTIMONIAL_SECONDS_PER_CARD,
        "problems": [asdict(card) for card in PROBLEMS],
        "steps": [asdict(card) for card in STEPS],
        "features": [asdict(card) for card in FEATURES],
        "targeting_sample": [asdict(tag) for tag in TARGETING_SAMPLE],
        "plans": [plan_out(plan) for plan in plans],
        "featured_plan": plan_out(featured_plan(plans)),
        "payments_on": payments_configured(),
        "display": display_as_dict(shown_prices(request)),
        "entry_plan": plan_out(
            min(monthly, key=lambda plan: plan.price) if monthly else None
        ),
        "tier_includes": [str(line) for line in TIER_INCLUDES],
        "questions": [asdict(item) for item in QUESTIONS],
    }


class ConsultIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=32)

    @field_validator("name")
    @classmethod
    def _squash(cls, value: str) -> str:
        return " ".join(value.split())


@router.post(
    "/consult",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": ConsultOut}},
)
def consult(body: ConsultIn, request: Request, db: Db) -> dict[str, Any]:
    from core.leads.phone import to_e164

    address = client_address(request)
    if spent(bucket=BUCKET, key=address, limit=CONSULT_PER_ADDRESS):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta yuboring.",
        )
    phone = to_e164(raw=body.phone, region=_region())
    if not phone:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Raqamni to'liq kiriting."
        )
    record(bucket=BUCKET, key=address, window_seconds=CONSULT_WINDOW_SECONDS)
    row = services.create_consult_request(
        db, name=body.name, phone_e164=phone, language=get_language()
    )
    db.commit()
    return {"sent": True, "id": str(row.id), "pixel_event": "Lead"}


class DeletionIn(BaseModel):
    email: EmailStr
    reason: str = Field(default="", max_length=1000)


def _status_url(code: str) -> str:
    return f"{settings.site_url}/data-deletion/status/{code}/"


@router.get("/data-deletion", responses={200: {"model": DeletionPageOut}})
def deletion_page() -> dict[str, Any]:
    return {"deletion_sla_days": DELETION_SLA_DAYS}


@router.post(
    "/data-deletion",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": DeletionCreatedOut}},
)
def data_deletion(body: DeletionIn, db: Db) -> dict[str, Any]:
    row = services.create_deletion_request(
        db,
        source=DeletionRequestSource.WEB_FORM,
        email=str(body.email),
        reason=body.reason,
    )
    db.commit()
    return {
        "confirmation_code": row.confirmation_code,
        "url": _status_url(row.confirmation_code),
    }


@router.get(
    "/data-deletion/status/{code}", responses={200: {"model": DeletionStatusOut}}
)
def deletion_status(code: str, db: Db) -> dict[str, Any]:
    try:
        row = selectors.get_by_confirmation_code(db, code)
    except DeletionRequestNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.message) from None
    return {
        "code": code,
        "status": row.status,
        "is_open": row.is_open,
        "created_at": row.created_at,
        "resolved_at": row.resolved_at,
        "deletion_sla_days": DELETION_SLA_DAYS,
    }


@router.get("/privacy", responses={200: {"model": PrivacyOut}})
def privacy() -> dict[str, Any]:
    return {"deletion_sla_days": DELETION_SLA_DAYS, "updated_at": LEGAL_UPDATED_AT}


@router.get("/terms", responses={200: {"model": TermsOut}})
def terms() -> dict[str, Any]:
    return {"updated_at": LEGAL_UPDATED_AT}


@router.get("/privacy/{business_id}", responses={200: {"model": BusinessPrivacyOut}})
def business_privacy(business_id: uuid.UUID, db: Db) -> dict[str, Any]:
    from app.modules.businesses.selectors import public_business

    business = public_business(db, business_id=business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return {
        "business": {"id": str(business.id), "name": business.name},
        "deletion_sla_days": DELETION_SLA_DAYS,
        "updated_at": ADVERTISER_POLICY_UPDATED_AT,
    }


@callbacks.post("/data-deletion/callback/", include_in_schema=False)
def meta_deletion_callback(db: Db, signed_request: str = Form("")) -> JSONResponse:
    try:
        row = services.process_meta_deletion_callback(db, signed_request=signed_request)
    except InvalidSignedRequest:
        return JSONResponse({"error": "invalid signed_request"}, status_code=400)
    db.commit()
    logger.info(
        "meta.deletion_callback.accepted",
        extra={"confirmation_code": row.confirmation_code},
    )
    return JSONResponse(
        {
            "url": _status_url(row.confirmation_code),
            "confirmation_code": row.confirmation_code,
        }
    )
