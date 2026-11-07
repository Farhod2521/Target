"""Editing what already runs: one advert's words and picture, one campaign's settings, a preview.

Registered on the campaigns router. A save opens changes through the same
services the switches use, so every guardrail and audit row is the same.
"""

import uuid
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from adskit.errors import ProviderError
from fastapi import HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common import throttle
from app.common.contract import Camel
from app.common.db import utcnow
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads import actions, selectors, services
from app.modules.ads.constants import (
    GEO_SEARCHES_PER_MINUTE,
    MAX_GEO_PLACES,
    MAX_GEO_SEARCH,
    ManagedLevel,
)
from app.modules.ads.contract.editing import CampaignPatch
from app.modules.ads.contract.launch.shapes import PlaceFound
from app.modules.ads.contract.shapes import (
    AdEdit,
    AdPreview,
    CampaignEdit,
    ControlState,
    DetailFound,
    EditLocale,
    ReachEstimate,
)
from app.modules.ads.inputs import Problems
from app.modules.ads.inputs.budget import budget_minor as checked_budget
from app.modules.ads.inputs.budget import cap_minor as checked_cap
from app.modules.ads.models import Campaign
from app.modules.ads.routers import _target, router
from app.modules.ads.schemas import (
    CampaignEditSaveOut,
)
from app.modules.ads.services.audience_search import (
    confirmed_detail,
    estimated_reach,
    search_detail,
    search_locales,
)
from app.modules.ads.services.locations import (
    campaign_places,
    confirmed_for_campaign,
    place_query,
)
from core.targeting import MAX_AGE, MIN_AGE, AudienceEdit
from core.targeting.audiences import EXCLUDE_KEY, INCLUDE_KEY, AudienceRef
from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import GeoChoice, GeoPlace, chosen_places, pins
from core.targeting.revise import (
    Detail,
    detail_is_open,
    detailed_of,
    excluded_detailed_of,
    excluded_places_of,
    revise,
)

GEO_SEARCH_BUCKET = "geo-search"
REACH_BUCKET = "campaign-reach"
REACHES_PER_MINUTE = 30
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


@router.post("/ads/{external_id}/edit", response_model=ControlState)
def ad_edit_save(
    external_id: str, body: AdEditIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Build the next advert from this one, and switch this one off.

    Answers its state: Meta's refusal comes later, in the worker.
    """
    from app.modules.ads.routers import control_state

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
    return control_state(db, user, level=ManagedLevel.AD, external_id=ad.external_id)


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
            "can_move": edit.audience.can_move,
            "places": [
                {"id": place.key, "name": place.name, "type": place.kind}
                for place in chosen_places(edit.audience.spec)
            ],
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
            "pin": _one_pin(edit.audience.spec),
            "excluded_places": [
                {"id": place.key, "name": place.name, "type": place.kind}
                for place in excluded_places_of(edit.audience.spec)
            ],
            "detailed": [asdict(row) for row in detailed_of(edit.audience.spec)],
            "excluded_detailed": [
                asdict(row) for row in excluded_detailed_of(edit.audience.spec)
            ],
            "detail_open": _detail_open(edit.audience),
            "included_lists": _held_lists(edit.audience.spec, INCLUDE_KEY),
            "excluded_lists": _held_lists(edit.audience.spec, EXCLUDE_KEY),
            "locales": list(edit.audience.spec.get("locales") or []),
            "category": _category(edit.campaign),
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


def _one_pin(spec: dict[str, Any]) -> dict[str, str] | None:
    """The point on the map; several, from Ads Manager, are read as none."""
    held = pins(spec)
    if len(held) != 1:
        return None
    return {"lat": str(held[0]["latitude"]), "lng": str(held[0]["longitude"])}


def _detail_open(target: Any) -> bool:
    return detail_is_open(target.spec) and not target.special


def _held_lists(spec: dict[str, Any], key: str) -> list[str]:
    return [str(row["id"]) for row in spec.get(key) or () if row.get("id")]


def _category(campaign: Any) -> str:
    return next(
        (
            name
            for name in campaign.special_ad_categories or ()
            if name and name != "NONE"
        ),
        "",
    )


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


class PlaceIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    type: Literal["city", "region", "country"]


class DetailIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(min_length=1, max_length=32)


class PinIn(BaseModel):
    lat: str = Field(min_length=1, max_length=32)
    lng: str = Field(min_length=1, max_length=32)


class AudienceSectionIn(BaseModel):
    age_min: int = Field(ge=MIN_AGE, le=MAX_AGE)
    age_max: int = Field(ge=MIN_AGE, le=MAX_AGE)
    genders: list[Literal[1, 2]] | None = Field(
        default=None, description="[] for everybody, [1] men, [2] women"
    )
    radius_km: int | None = None
    keep_interests: bool = True
    places: list[PlaceIn] | None = Field(
        default=None, description="Where it reaches, whole; none leaves it as it is."
    )
    pin: PinIn | None = Field(default=None, description="One point instead of places.")
    excluded_places: list[PlaceIn] | None = None
    detailed: list[DetailIn] | None = None
    excluded_detailed: list[DetailIn] | None = None
    included_lists: list[str] | None = None
    excluded_lists: list[str] | None = None
    locales: list[int] | None = None


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
    if body.audience is not None and edit.audience is not None:
        audience = _audience_edit(
            db, user=user, edit=edit, wanted=body.audience, errors=errors
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


def _audience_edit(
    db: Session,
    *,
    user: User,
    edit: Any,
    wanted: AudienceSectionIn,
    errors: dict[str, str],
) -> AudienceEdit | None:
    """The form's audience as one edit; what may not change now is left out."""
    from core.targeting import MAX_RADIUS_KM

    target = edit.audience
    found: AudienceEdit | None = None
    if target.can_change:
        if wanted.age_min > wanted.age_max:
            errors["audience"] = "Yosh oralig'i teskari kiritilgan."
        found = AudienceEdit(
            age_min=wanted.age_min,
            age_max=wanted.age_max,
            genders=tuple(wanted.genders)
            if wanted.genders is not None and target.allows_gender
            else None,
            keep_interests=wanted.keep_interests if target.sketch.interests else True,
        )
        found = _people(
            db, user=user, edit=edit, wanted=wanted, found=found, errors=errors
        )
    if target.can_move:
        found = found or AudienceEdit()
        radius = (
            wanted.radius_km
            if target.sketch.geo == "around" or wanted.pin is not None
            else None
        )
        if radius is not None and not target.min_radius_km <= radius <= MAX_RADIUS_KM:
            errors["audience"] = "Masofa %s-%s km oralig'ida bo'lishi kerak." % (
                target.min_radius_km,
                MAX_RADIUS_KM,
            )
        found = replace(found, radius_km=radius)
        found = _where(db, edit=edit, wanted=wanted, found=found, errors=errors)
    return None if found is None or found.is_empty else found


def _where(
    db: Session,
    *,
    edit: Any,
    wanted: AudienceSectionIn,
    found: AudienceEdit,
    errors: dict[str, str],
) -> AudienceEdit:
    if wanted.places is not None:
        places = _wanted_places(db, edit=edit, picked=wanted.places)
        if places is None:
            errors["places"] = "Joylardan birini qidiruvdan qayta tanlang."
        else:
            found = replace(found, places=places)
    if wanted.pin is not None:
        point = GeoChoice(mode="around", lat=wanted.pin.lat, lng=wanted.pin.lng)
        if not point.has_pin:
            errors["places"] = "Xaritadan nuqta tanlang."
        else:
            found = replace(found, pin=(wanted.pin.lat, wanted.pin.lng))
    return found


def _people(
    db: Session,
    *,
    user: User,
    edit: Any,
    wanted: AudienceSectionIn,
    found: AudienceEdit,
    errors: dict[str, str],
) -> AudienceEdit:
    spec = edit.audience.spec
    if wanted.detailed is not None or wanted.excluded_detailed is not None:
        if not _detail_open(edit.audience):
            errors["detailed"] = "Bu auditoriyada qiziqishlar shu yerda o'zgarmaydi."
        else:
            found = _details(db, edit=edit, wanted=wanted, found=found, errors=errors)
    if wanted.excluded_places is not None:
        held = {(row.kind, row.key): row for row in excluded_places_of(spec)}
        places = _picked_places(db, edit=edit, held=held, picked=wanted.excluded_places)
        if places is None or len(wanted.excluded_places) > MAX_GEO_PLACES:
            errors["places"] = "Joylardan birini qidiruvdan qayta tanlang."
        else:
            found = replace(found, excluded_places=places)
    if wanted.included_lists is not None or wanted.excluded_lists is not None:
        lists = _wanted_lists(db, user=user, edit=edit, wanted=wanted)
        if lists is None:
            errors["lists"] = "Bu auditoriyani tanlab bo'lmaydi."
        else:
            found = replace(found, included_lists=lists[0], excluded_lists=lists[1])
    if wanted.locales is not None:
        found = replace(found, locales=tuple(wanted.locales))
    return found


def _details(
    db: Session,
    *,
    edit: Any,
    wanted: AudienceSectionIn,
    found: AudienceEdit,
    errors: dict[str, str],
) -> AudienceEdit:
    spec = edit.audience.spec
    if wanted.detailed is not None:
        rows = _wanted_detail(
            db, edit=edit, picked=wanted.detailed, held=detailed_of(spec)
        )
        if rows is None:
            errors["detailed"] = "Qiziqishlardan birini qidiruvdan qayta tanlang."
        else:
            found = replace(found, detailed=rows)
    if wanted.excluded_detailed is not None:
        rows = _wanted_detail(
            db,
            edit=edit,
            picked=wanted.excluded_detailed,
            held=excluded_detailed_of(spec),
        )
        if rows is None:
            errors["detailed"] = "Qiziqishlardan birini qidiruvdan qayta tanlang."
        else:
            found = replace(found, excluded_detailed=rows)
    return found


def _wanted_detail(
    db: Session, *, edit: Any, picked: list[DetailIn], held: tuple[Detail, ...]
) -> tuple[Detail, ...] | None:
    """A row the audience has stays; a new one was searched."""
    kept = {(row.kind, row.id): row for row in held}
    new = [row for row in picked if (row.kind, row.id) not in kept]
    found = confirmed_detail(
        db, campaign=edit.campaign, picked=[row.model_dump() for row in new]
    )
    if found is None:
        return None
    fresh = {(row.kind, row.id): row for row in found}
    return tuple(
        kept.get((row.kind, row.id)) or fresh[(row.kind, row.id)] for row in picked
    )


def _wanted_lists(
    db: Session, *, user: User, edit: Any, wanted: AudienceSectionIn
) -> tuple[tuple[AudienceRef, ...], tuple[AudienceRef, ...]] | None:
    """Both sides as refs: a list it holds stays, another must be this account's and usable."""
    from app.modules.integrations.selectors.audiences import targets_for

    spec = edit.audience.spec
    held = {*_held_lists(spec, INCLUDE_KEY), *_held_lists(spec, EXCLUDE_KEY)}
    options = {
        row.external_id: row
        for row in targets_for(
            db,
            owner=user,
            account=edit.campaign.ad_account,
            special_ad_category=_category(edit.campaign),
        )
    }
    sides = (
        wanted.included_lists
        if wanted.included_lists is not None
        else _held_lists(spec, INCLUDE_KEY),
        wanted.excluded_lists
        if wanted.excluded_lists is not None
        else _held_lists(spec, EXCLUDE_KEY),
    )
    for key in {*sides[0], *sides[1]}:
        option = options.get(key)
        if key not in held and (option is None or not option.is_usable):
            return None

    def refs(keys: list[str]) -> tuple[AudienceRef, ...]:
        return tuple(
            AudienceRef(
                external_id=key,
                label=options[key].label if key in options else "",
                is_lookalike=options[key].is_lookalike if key in options else False,
            )
            for key in keys
        )

    return refs(sides[0]), refs(sides[1])


def _wanted_places(
    db: Session, *, edit: Any, picked: list[PlaceIn]
) -> tuple[GeoPlace, ...] | None:
    """What the form names: a place the audience has stays, a new one was searched."""
    held = {
        (place.kind, place.key): place for place in chosen_places(edit.audience.spec)
    }
    places = _picked_places(db, edit=edit, held=held, picked=picked)
    if not picked or len(picked) > MAX_GEO_PLACES:
        return None
    return places


def _picked_places(
    db: Session,
    *,
    edit: Any,
    held: dict[tuple[str, str], GeoPlace],
    picked: list[PlaceIn],
) -> tuple[GeoPlace, ...] | None:
    new = [row for row in picked if (row.type, row.id) not in held]
    found = confirmed_for_campaign(
        db, campaign=edit.campaign, picked=[row.model_dump() for row in new]
    )
    if found is None:
        return None
    fresh = {(place.kind, place.key): place for place in found}
    return tuple(
        held.get((row.type, row.id)) or fresh[(row.type, row.id)] for row in picked
    )


@router.get("/{campaign_id}/locations", response_model=list[PlaceFound])
def campaign_locations(
    campaign_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    q: str = Query("", max_length=MAX_GEO_SEARCH),
    country: str = Query("", pattern="^([A-Za-z]{2})?$"),
) -> list[PlaceFound]:
    """The place search for a running audience, as the launch's editor has it."""
    campaign = selectors.campaign_detail(db, owner=user, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kampaniya topilmadi.")
    query = place_query(q)
    if not query:
        return []
    if not throttle.hit(
        bucket=GEO_SEARCH_BUCKET,
        key=str(user.id),
        limit=GEO_SEARCHES_PER_MINUTE,
        window_seconds=60,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
        )
    rows = campaign_places(db, campaign=campaign, query=query, country_code=country)
    return [
        PlaceFound(
            id=row["key"],
            name=row["name"],
            type=row["kind"],
            context=row["context"],
            country_code=row["country_code"],
        )
        for row in rows
    ]


def _searched_campaign(db: Session, *, user: User, campaign_id: uuid.UUID) -> Campaign:
    """The campaign a search is for, once this person has not asked too often."""
    campaign = selectors.campaign_detail(db, owner=user, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kampaniya topilmadi.")
    if not throttle.hit(
        bucket=GEO_SEARCH_BUCKET,
        key=str(user.id),
        limit=GEO_SEARCHES_PER_MINUTE,
        window_seconds=60,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
        )
    return campaign


@router.get("/{campaign_id}/targeting-search", response_model=list[DetailFound])
def campaign_detail_search(
    campaign_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    q: str = Query("", max_length=MAX_GEO_SEARCH),
) -> list[dict[str, Any]]:
    """Interests, behaviours and life events a running audience may take."""
    query = place_query(q)
    if not query:
        return []
    campaign = _searched_campaign(db, user=user, campaign_id=campaign_id)
    return search_detail(db, campaign=campaign, query=query)


@router.get("/{campaign_id}/languages", response_model=list[EditLocale])
def campaign_language_search(
    campaign_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    q: str = Query("", max_length=MAX_GEO_SEARCH),
) -> list[dict[str, Any]]:
    """The languages a running audience may be narrowed to."""
    query = place_query(q)
    if not query:
        return []
    campaign = _searched_campaign(db, user=user, campaign_id=campaign_id)
    return search_locales(campaign=campaign, query=query)


NO_ESTIMATE: dict[str, Any] = {
    "available": False,
    "ready": True,
    "lower": 0,
    "upper": 0,
}


@router.post("/{campaign_id}/reach", response_model=ReachEstimate)
def campaign_reach(
    campaign_id: uuid.UUID, body: CampaignPatch, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """How many people the form as it stands would reach. Nothing is saved or sent."""
    from app.modules.ads.contract.editing import changed_sections
    from app.modules.ads.exceptions import ConnectionUnusable, NoAdAccount

    edit, form = _sections(db, user, campaign_id, body.group or "")
    if edit.audience is None:
        return NO_ESTIMATE
    if not throttle.hit(
        bucket=REACH_BUCKET,
        key=str(user.id),
        limit=REACHES_PER_MINUTE,
        window_seconds=60,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
        )
    group = next(
        row
        for row in edit.campaign.adsets
        if row.external_id == edit.audience.external_id
    )
    errors: dict[str, str] = {}
    sent = (changed_sections(form["sections"], body) or {}).get("audience")
    audience = (
        _audience_edit(
            db,
            user=user,
            edit=edit,
            wanted=AudienceSectionIn(**sent),
            errors=errors,
        )
        if sent
        else None
    )
    if errors:
        return NO_ESTIMATE
    try:
        spec = (
            revise(edit.audience.spec, edit=audience, special=edit.audience.special)
            if audience is not None
            else dict(edit.audience.spec)
        )
        reach = estimated_reach(campaign=edit.campaign, group=group, targeting=spec)
    except (InvalidTargeting, ProviderError, NoAdAccount, ConnectionUnusable):
        return NO_ESTIMATE
    return {
        "available": reach.available,
        "ready": reach.ready,
        "lower": reach.lower or 0,
        "upper": reach.upper or 0,
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
    from app.modules.ads.contract.editing import (
        FORM_FIELDS,
        adjusted_sentences,
        changed_sections,
    )
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
    state = control_state(db, user, level=level, external_id=external_id)
    return state | {"notes": adjusted_sentences(saved["adjustments"])}


class CampaignNameIn(Camel):
    name: str = Field(description="The new name; spaces are collapsed.")


@router.post("/{campaign_id}/name", response_model=ControlState)
def campaign_rename(
    campaign_id: uuid.UUID, body: CampaignNameIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """TZ 4: a running campaign's name, sent to Meta like any other change.

    Answers the campaign's state, followed like any press. An empty name or
    one over ``LAUNCH_NAME_MAX`` characters is refused under ``name``.
    """
    from app.common.exceptions import InputRefused
    from app.modules.ads.exceptions import CampaignNameEmpty, CampaignNameTooLong
    from app.modules.ads.routers import control_state

    campaign = selectors.campaign_detail(db, owner=user, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kampaniya topilmadi.")
    try:
        actions.request(
            db,
            user=user,
            ask=actions.Rename(external_id=campaign.external_id, name=body.name),
        )
    except (CampaignNameEmpty, CampaignNameTooLong) as exc:
        raise InputRefused({"name": str(exc)}) from None
    db.commit()
    return control_state(
        db, user, level=ManagedLevel.CAMPAIGN, external_id=campaign.external_id
    )


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
