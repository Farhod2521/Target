"""Editing what already runs: one advert's words and picture, one campaign's settings, a preview.

Registered on the campaigns router. A save opens changes through the same
services the switches use, so every guardrail and audit row is the same.
"""

import uuid
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.contract import Camel
from app.common.db import utcnow
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads import actions, selectors, services
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.contract.editing import CampaignPatch
from app.modules.ads.contract.shapes import (
    AdEdit,
    AdPreview,
    CampaignEdit,
    ControlState,
)
from app.modules.ads.inputs import Problems
from app.modules.ads.inputs.budget import budget_minor as checked_budget
from app.modules.ads.inputs.budget import cap_minor as checked_cap
from app.modules.ads.routers import _target, router
from app.modules.ads.schemas import (
    CampaignEditSaveOut,
)
from core.targeting import MAX_AGE, MIN_AGE

SENT_SETTINGS = "O'zgarish yuborildi. Bir necha soniyada ko'rinadi."
HEADLINE_LIMIT = 255
MESSAGE_LIMIT = 2000
DEFAULT_ZONE = "Asia/Tashkent"
GROUP_Q = Query(
    "", description="An ad set's Meta id: edit that group only. Empty for the campaign."
)


def _ad_forms(db: Session, user: User, ad: Any) -> dict[str, Any] | None:
    """The form this advert opens now and the page's others, or nothing."""
    from app.modules.ads.services.swap import form_page
    from app.modules.leads.selectors import forms_by_external_id, usable_forms

    page = form_page(db, owner=user, ad=ad)
    if page is None:
        return None
    current = forms_by_external_id(
        db, owner=user, provider=ad.provider, external_ids=[ad.lead_form_external_id]
    )[ad.lead_form_external_id]
    choices = usable_forms(db, owner=user, page=page, limit=None)
    return {
        "current_id": ad.lead_form_external_id,
        "current_name": current.name,
        "options": [
            {
                "external_id": row.external_id,
                "name": row.name,
                "questions": list(row.questions),
            }
            for row in choices.options
            if row.external_id != ad.lead_form_external_id
        ],
    }


def _ad_library(db: Session, user: User, ad: Any) -> list[Any]:
    from app.modules.ads.services.swap import SWAPPABLE_KINDS

    return selectors.media_library(
        db,
        owner=user,
        provider=ad.provider,
        ad_account=selectors.account_of(target=ad, level=ManagedLevel.AD),
        kinds=SWAPPABLE_KINDS,
    )


@router.get("/ads/{external_id}/edit", response_model=AdEdit)
def ad_edit(external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    """What this advert says now, the pictures it may be given, and the forms it may open."""
    from app.modules.ads.contract.adverts import ad_edit_form

    ad = _target(db, user, ManagedLevel.AD, external_id)
    content = selectors.creative_of(db, owner=user, ad=ad)
    return ad_edit_form(
        ad,
        initial={
            "message": getattr(content, "message", "") or "",
            "headline": getattr(content, "headline", "") or "",
            "description": getattr(content, "description", "") or "",
        },
        can_swap=bool(getattr(content, "story_raw", None)),
        library=[selectors.asset_row(row) for row in _ad_library(db, user, ad)],
        forms=_ad_forms(db, user, ad),
        limits={"headline": HEADLINE_LIMIT, "message": MESSAGE_LIMIT},
        early_hours=selectors.hours_to_wait(
            db,
            owner=user,
            level=ManagedLevel.AD,
            external_id=ad.external_id,
            now=utcnow(),
        ),
    )


class AdEditIn(Camel):
    message: str = Field(default="", max_length=MESSAGE_LIMIT)
    headline: str = Field(default="", max_length=HEADLINE_LIMIT)
    description: str = Field(default="", max_length=HEADLINE_LIMIT)
    picture: str | None = Field(
        default=None, description="A library row id; empty keeps the picture"
    )
    lead_form: str | None = Field(
        default=None, description="A form id from `forms.options`; empty keeps it"
    )


@router.post("/ads/{external_id}/edit", status_code=status.HTTP_204_NO_CONTENT)
def ad_edit_save(external_id: str, body: AdEditIn, db: Db, user: CurrentUser) -> None:
    """Build the next advert from this one, and switch this one off."""
    ad = _target(db, user, ManagedLevel.AD, external_id)
    if not any(
        word.strip() for word in (body.message, body.headline, body.description)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reklama hech bo'lmasa bitta jumla aytishi kerak.",
        )
    if (body.picture or "") and (body.picture or "") not in {
        str(row.id) for row in _ad_library(db, user, ad)
    }:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bu rasm kutubxonada yo'q."
        )
    if body.lead_form or "":
        offered = _ad_forms(db, user, ad)
        if offered is None or (body.lead_form or "") not in {
            row["external_id"] for row in offered["options"]
        }:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bu formani tanlab bo'lmaydi.",
            )
    actions.request(
        db,
        user=user,
        ask=actions.NewAdvert(
            external_id=ad.external_id,
            message=body.message,
            headline=body.headline,
            description=body.description,
            asset_id=(body.picture or ""),
            lead_form_id=(body.lead_form or ""),
        ),
    )
    db.commit()


def _editable(db: Session, user: User, campaign_id: uuid.UUID, group: str) -> Any:
    campaign = selectors.campaign_detail(db, owner=user, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kampaniya topilmadi.")
    edit = selectors.editable(db, campaign=campaign, group=group)
    if edit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Guruh topilmadi.")
    return edit


def _major(amount_minor: int | None, places: int) -> str | None:
    return None if amount_minor is None else str(Decimal(amount_minor).scaleb(-places))


def _zone(db: Session, user: User) -> str:
    from app.modules.businesses.selectors import business_timezone

    return business_timezone(db, owner=user) or DEFAULT_ZONE


def _sections(
    db: Session, user: User, campaign_id: uuid.UUID, group: str
) -> tuple[Any, dict[str, Any]]:
    """Every section this campaign has, and which of them may be changed right now."""
    from zoneinfo import ZoneInfo

    from core.targeting import MAX_AGE, MAX_RADIUS_KM, MIN_AGE
    from core.targeting.geo import DISTANCE_UNIT

    edit = _editable(db, user, campaign_id, group)
    sections: dict[str, Any] = {}
    if edit.budget is not None:
        controls = edit.budget.controls
        places = provider_money(provider=controls.provider).decimal_places(
            controls.currency
        )
        sections["budget"] = {
            "level": edit.budget.level,
            "external_id": edit.budget.external_id,
            "can_change": controls.can_budget,
            "warns_learning": controls.warns_learning,
            "currency": controls.currency,
            "places": places,
            "current": _major(controls.daily_budget_minor, places),
            "current_minor": controls.daily_budget_minor,
            "floor_minor": controls.floor_minor,
        }
    if edit.audience is not None:
        sketch = edit.audience.sketch
        sections["audience"] = {
            "external_id": edit.audience.external_id,
            "can_change": edit.audience.can_change,
            "is_learning": edit.audience.is_learning,
            "allows_gender": edit.audience.allows_gender,
            "age_min": sketch.age_min or MIN_AGE,
            "age_max": sketch.age_max or MAX_AGE,
            "age_bounds": [MIN_AGE, MAX_AGE],
            "genders": {"male": [1], "female": [2]}.get(sketch.genders, []),
            "offers_radius": sketch.geo == "around"
            and sketch.radius_unit in ("", DISTANCE_UNIT),
            "radius_km": sketch.radius,
            "radius_bounds": [edit.audience.min_radius_km, MAX_RADIUS_KM],
            "has_interests": bool(sketch.interests),
        }
    if edit.limits is not None:
        limits = edit.limits
        places = provider_money(provider=str(edit.campaign.provider)).decimal_places(
            limits.currency
        )
        zone = _zone(db, user)
        today = utcnow().astimezone(ZoneInfo(zone)).date()
        sections["limits"] = {
            "can_change": limits.can_change,
            "offers_end_time": limits.offers_end_time,
            "offers_spend_cap": limits.offers_spend_cap,
            "end_date": limits.end_time.date() if limits.end_time else None,
            "earliest_end_date": today + timedelta(days=1),
            "spend_cap": _major(limits.spend_cap_minor, places)
            if limits.spend_cap_minor
            else None,
            "currency": limits.currency,
            "timezone": zone,
        }
    target, level = (
        (edit.group, ManagedLevel.ADSET)
        if edit.group is not None
        else (edit.campaign, ManagedLevel.CAMPAIGN)
    )
    return edit, {
        "campaign": {"id": str(edit.campaign.id), "name": edit.campaign.name},
        "groups": edit.groups,
        "sections": sections,
        "early_hours": selectors.hours_to_wait(
            db,
            owner=user,
            level=level,
            external_id=str(target.external_id),
            now=utcnow(),
        ),
    }


@router.get("/{campaign_id}/edit", response_model=CampaignEdit)
def campaign_edit(
    campaign_id: uuid.UUID, db: Db, user: CurrentUser, group: str = GROUP_Q
) -> dict[str, Any]:
    """The edit form as it is drawn: today's values, the bounds, and what is locked."""
    from app.modules.ads.contract.editing import edit_form

    edit, form = _sections(db, user, campaign_id, group)
    return edit_form(db, owner=user, edit=edit, form=form)


class BudgetSectionIn(BaseModel):
    daily_budget: Decimal = Field(gt=0)


class AudienceSectionIn(BaseModel):
    age_min: int = Field(ge=MIN_AGE, le=MAX_AGE)
    age_max: int = Field(ge=MIN_AGE, le=MAX_AGE)
    genders: list[Literal[1, 2]] | None = Field(
        default=None, description="[] for everybody, [1] men, [2] women"
    )
    radius_km: int | None = None
    keep_interests: bool = True


class LimitsSectionIn(BaseModel):
    end_date: date | None = None
    spend_cap: Decimal | None = Field(default=None, ge=0)


class CampaignEditIn(BaseModel):
    budget: BudgetSectionIn | None = None
    audience: AudienceSectionIn | None = None
    limits: LimitsSectionIn | None = None


def _save(
    db: Session,
    user: User,
    campaign_id: uuid.UUID,
    group: str,
    body: CampaignEditIn,
) -> dict[str, Any]:
    """Every section checked together, then written one by one; what each became is said."""
    from zoneinfo import ZoneInfo

    from core.targeting import MAX_RADIUS_KM, AudienceEdit

    edit = _editable(db, user, campaign_id, group)
    errors: dict[str, str] = {}
    problems = Problems()
    budget_minor: int | None = None
    cap_minor: int | None = None
    end_time: datetime | None = None
    audience = None
    if (
        body.budget is not None
        and edit.budget is not None
        and edit.budget.controls.can_budget
    ):
        controls = edit.budget.controls
        budget_minor = checked_budget(
            body.budget.daily_budget,
            currency=controls.currency,
            money=provider_money(provider=controls.provider),
            floor_minor=controls.floor_minor,
            problems=problems,
            field="budget",
        )
    if (
        body.audience is not None
        and edit.audience is not None
        and edit.audience.can_change
    ):
        wanted = body.audience
        sketch = edit.audience.sketch
        if wanted.age_min > wanted.age_max:
            errors["audience"] = "Yosh oralig'i teskari kiritilgan."
        radius = wanted.radius_km if sketch.geo == "around" else None
        if radius is not None and not (
            edit.audience.min_radius_km <= radius <= MAX_RADIUS_KM
        ):
            errors["audience"] = "Masofa %s-%s km oralig'ida bo'lishi kerak." % (
                edit.audience.min_radius_km,
                MAX_RADIUS_KM,
            )
        audience = AudienceEdit(
            age_min=wanted.age_min,
            age_max=wanted.age_max,
            genders=tuple(wanted.genders)
            if wanted.genders is not None and edit.audience.allows_gender
            else None,
            radius_km=radius,
            keep_interests=wanted.keep_interests if sketch.interests else True,
        )
    if body.limits is not None and edit.limits is not None and edit.limits.can_change:
        zone = ZoneInfo(_zone(db, user))
        if body.limits.end_date is not None and edit.limits.offers_end_time:
            if body.limits.end_date <= utcnow().astimezone(zone).date():
                errors["limits"] = (
                    "Ertangi kundan boshlab sana tanlang. "
                    "To'xtatish uchun «To'xtatish» tugmasi bor."
                )
            end_time = datetime.combine(
                body.limits.end_date, time(23, 59, 59), tzinfo=zone
            )
        if body.limits.spend_cap is not None and edit.limits.offers_spend_cap:
            cap_minor = checked_cap(
                body.limits.spend_cap,
                currency=edit.limits.currency,
                money=provider_money(provider=str(edit.campaign.provider)),
                problems=problems,
                field="limits",
            )
    errors = problems.found | errors
    if errors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"errors": errors}
        )
    outcome = services.change_settings(
        db,
        user=user,
        editable=edit,
        daily_budget_minor=budget_minor,
        audience=audience,
        end_time=end_time,
        spend_cap_minor=cap_minor,
    )
    db.commit()
    return {
        "queued": list(outcome.queued),
        "refused": outcome.refused,
        "adjustments": [asdict(note) for note in outcome.adjustments],
        "message": SENT_SETTINGS if outcome.queued else "O'zgarish kiritilmadi.",
    }


@router.post("/{campaign_id}/edit", responses={200: {"model": CampaignEditSaveOut}})
def campaign_edit_save(
    campaign_id: uuid.UUID,
    body: CampaignEditIn,
    db: Db,
    user: CurrentUser,
    group: str = GROUP_Q,
) -> dict[str, Any]:
    return _save(db, user, campaign_id, group, body)


@router.patch("/{campaign_id}", response_model=ControlState | None)
def campaign_patch(
    campaign_id: uuid.UUID, body: CampaignPatch, db: Db, user: CurrentUser
) -> Any:
    """The edit form saved whole: only what changed and may change is sent.

    Answers the edited object's state, followed like any press; nothing to
    send is a 204.
    """
    from fastapi import Response

    from app.common.exceptions import InputRefused
    from app.modules.ads.contract.editing import FORM_FIELDS, changed_sections
    from app.modules.ads.exceptions import PressRefused
    from app.modules.ads.routers import control_state

    group = body.group or ""
    edit, form = _sections(db, user, campaign_id, group)
    sections = changed_sections(form["sections"], body)
    if sections is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        saved = _save(db, user, campaign_id, group, CampaignEditIn(**sections))
    except HTTPException as exc:
        errors = exc.detail.get("errors", {}) if isinstance(exc.detail, dict) else {}
        raise InputRefused(
            {FORM_FIELDS.get(key, key): words for key, words in errors.items()}
        ) from None
    if saved["refused"]:
        raise PressRefused.on(
            {
                FORM_FIELDS.get(key, key): words
                for key, words in saved["refused"].items()
            },
            message=saved["message"],
        )
    level, external_id = _followed(form["sections"], sent=sections, edit=edit)
    return control_state(db, user, level=level, external_id=external_id)


def _followed(
    sections: dict[str, Any], *, sent: dict[str, Any], edit: Any
) -> tuple[str, str]:
    """The object a saved form changed, whose state the row follows."""
    if "budget" in sent:
        return sections["budget"]["level"], sections["budget"]["external_id"]
    if "audience" in sent:
        return ManagedLevel.ADSET, sections["audience"]["external_id"]
    if edit.group is not None:
        return ManagedLevel.ADSET, str(edit.group.external_id)
    return ManagedLevel.CAMPAIGN, str(edit.campaign.external_id)


@router.get("/ads/{external_id}/preview", response_model=AdPreview)
def preview(external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    """What this advert looks like: the mirror's own card always, Meta's frame once it arrives."""
    from app.modules.ads.constants import MAX_PREVIEW_POLLS, PREVIEW_AD_FORMAT
    from app.modules.ads.contract.adverts import ad_preview, preview_tries

    ad = _target(db, user, ManagedLevel.AD, external_id)
    found = selectors.fresh_preview(db, owner=user, external_id=external_id)
    tries = preview_tries(user, external_id, settled=found is not None)
    if found is None and tries == 0:
        from app.modules.ads.tasks import fetch_preview_task

        fetch_preview_task.delay(str(user.id), external_id, PREVIEW_AD_FORMAT)
    selectors.with_content(db, owner=user, ads=[ad])
    return ad_preview(
        db,
        owner=user,
        ad=ad,
        content=getattr(ad, "content", None),
        frame=found,
        loading=found is None and tries < MAX_PREVIEW_POLLS,
    )
