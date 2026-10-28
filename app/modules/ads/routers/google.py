"""The Google Ads screen and its Search wizard.

Everything here is not found for an owner Google Ads is not switched on
for. The screen lists one account's campaigns for a period; a press
(``/switch``, ``/budget``, ``/delete``, ``/refresh``) is queued and the
screen read again shows where it got to.

The wizard is three steps on one preparation: answers (goal, site, phone,
places, budget), words (keywords and texts the AI wrote, as edited), and
review with «Yaratish».
"""

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.exceptions import NotFound
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    GOOGLE_FAILURES,
    GOOGLE_GOAL_LABELS,
    GoogleGoal,
    ManagedLevel,
)
from app.modules.ads.exceptions import GoogleBudgetRequired
from app.modules.ads.models import GoogleLaunch
from app.modules.ads.routers.launch_common import committed, encoded
from app.modules.ads.selectors.audiences_chosen import area_options
from app.modules.ads.selectors.google import (
    DEFAULT_PERIOD,
    PERIODS,
    google_launch_for,
    google_screen,
    keyword_rows,
    launch_profile,
    search_preview,
)
from app.modules.ads.services import google as google_services
from app.modules.ads.services.manage import (
    request_budget,
    request_pause,
    request_resume,
)
from app.modules.ads.services.removal import request_delete
from app.modules.integrations.selectors.google import (
    current_google_account,
    google_ads_on,
)

router = APIRouter(prefix="/google", tags=["google ads"])
PERIOD_LABELS = (("today", "Bugun"), ("7", "7 kun"), ("30", "30 kun"))
LEVELS = frozenset({ManagedLevel.CAMPAIGN, ManagedLevel.ADSET})


class SwitchIn(BaseModel):
    level: Literal["campaign", "adset"]
    external_id: str
    wanted: Literal["pause", "resume"]


class BudgetIn(BaseModel):
    external_id: str
    budget: str = Field(description="Whole currency units, as typed.")


class DeleteIn(BaseModel):
    external_id: str


class AnswersIn(BaseModel):
    goal: str = ""
    final_url: str = Field("", max_length=1000)
    phone: str = Field("", max_length=32)
    areas: list[str] = Field(default_factory=list)
    budget: str = ""


class WordsIn(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    headlines: list[str] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)
    path1: str = Field("", max_length=15)
    path2: str = Field("", max_length=15)


def _switched_on(user: User) -> None:
    if not google_ads_on(user=user):
        raise NotFound("Sahifa topilmadi.")


def typed_budget(*, provider: str, currency: str, typed: str) -> int:
    """A typed amount in whole currency as the account's minor units."""
    try:
        amount = Decimal(typed.replace(",", ".").replace(" ", "").strip())
    except InvalidOperation as exc:
        raise GoogleBudgetRequired from exc
    if not amount.is_finite() or amount <= 0:
        raise GoogleBudgetRequired
    rules = provider_money(provider=provider)
    return int(rules.to_minor(amount=amount, currency=currency))


def _screen(db: Session, *, user: User, period: str) -> dict[str, Any]:
    chosen = period if period in PERIODS else DEFAULT_PERIOD
    return encoded(
        {
            "period": chosen,
            "periods": [{"value": key, "label": label} for key, label in PERIOD_LABELS],
            "screen": google_screen(db, owner=user, period=chosen),
        }
    )


@router.get("")
def screen(
    db: Db, user: CurrentUser, period: str = Query(DEFAULT_PERIOD)
) -> dict[str, Any]:
    """One account's campaigns and groups, with their figures for the period."""
    _switched_on(user)
    return _screen(db, user=user, period=period)


@router.post("/switch")
def switch(body: SwitchIn, db: Db, user: CurrentUser) -> dict[str, str]:
    """Stop or start one campaign or group."""
    _switched_on(user)
    change = request_pause if body.wanted == "pause" else request_resume
    committed(
        db,
        lambda: change(db, user=user, level=body.level, external_id=body.external_id),
    )
    return {"detail": "Google'ga yuborildi. Holat bir necha soniyada yangilanadi."}


@router.post("/budget")
def budget(body: BudgetIn, db: Db, user: CurrentUser) -> dict[str, str]:
    """A campaign's daily figure. Google keeps a budget on campaigns only."""
    _switched_on(user)
    account = current_google_account(db, owner=user)
    if account is None:
        raise NotFound("Google Ads akkaunti ulanmagan.")
    amount = typed_budget(
        provider=account.provider, currency=account.currency, typed=body.budget
    )
    committed(
        db,
        lambda: request_budget(
            db,
            user=user,
            level=ManagedLevel.CAMPAIGN,
            external_id=body.external_id,
            daily_budget_minor=amount,
        ),
    )
    return {"detail": "Google'ga yuborildi. Byudjet tez orada yangilanadi."}


@router.post("/delete")
def delete(body: DeleteIn, db: Db, user: CurrentUser) -> dict[str, str]:
    """Remove a campaign for good, after the dialog has asked."""
    _switched_on(user)
    committed(db, lambda: request_delete(db, user=user, external_id=body.external_id))
    return {"detail": "Google'ga yuborildi. Kampaniya o'chiriladi."}


@router.post("/refresh")
def refresh(db: Db, user: CurrentUser) -> dict[str, str]:
    """Read the account from Google again."""
    _switched_on(user)
    committed(db, lambda: google_services.request_google_refresh(db, user=user))
    return {"detail": "Yangilanmoqda. Bir daqiqada tayyor bo'ladi."}


# -- the Search wizard -----------------------------------------------------------------


def _launch(db: Session, *, user: User, launch_id: uuid.UUID) -> GoogleLaunch:
    _switched_on(user)
    found = google_launch_for(db, owner=user, launch_id=launch_id)
    if found is None:
        raise NotFound("Tayyorlash topilmadi.")
    return found


def _common(launch: GoogleLaunch) -> dict[str, Any]:
    return {
        "id": str(launch.id),
        "status": launch.status,
        "goal": launch.goal,
        "goal_label": GOOGLE_GOAL_LABELS.get(launch.goal, "") if launch.goal else "",
        "currency": launch.currency,
        "daily_budget_minor": launch.daily_budget_minor,
        "final_url": launch.final_url,
        "phone": launch.phone,
        "places": launch.places,
        "error_code": launch.error_code,
        "failure": GOOGLE_FAILURES.get(launch.error_code, ""),
        "dry_run": launch.dry_run,
        "ai_written_at": launch.ai_written_at,
        "created_refs": launch.created_refs,
        "finished_at": launch.finished_at,
    }


@router.post("/launch", status_code=status.HTTP_201_CREATED)
def start_launch(db: Db, user: CurrentUser) -> dict[str, Any]:
    """«Reklama berish» on the Google screen."""
    _switched_on(user)
    launch = committed(db, lambda: google_services.start_google_launch(db, user=user))
    return encoded(_common(launch))


@router.get("/launch/{launch_id}/answers")
def answers(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Step one: goal, site, phone, places, budget."""
    launch = _launch(db, user=user, launch_id=launch_id)
    profile = launch_profile(db, launch=launch)
    country = profile.country_code if profile else ""
    places = provider_money(provider=launch.ad_account.provider).decimal_places(
        launch.currency
    )
    return encoded(
        _common(launch)
        | {
            "goals": [
                {"value": value, "label": label} for value, label in GoogleGoal.choices
            ],
            "areas": area_options(db, country_code=country) if country else [],
            "chosen": sorted({str(row.get("area")) for row in launch.places}),
            "budget": Decimal(launch.daily_budget_minor).scaleb(-places)
            if launch.daily_budget_minor
            else None,
            "step": 1,
        }
    )


@router.post("/launch/{launch_id}/answers")
def save_answers(
    launch_id: uuid.UUID, body: AnswersIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    launch = _launch(db, user=user, launch_id=launch_id)
    profile = launch_profile(db, launch=launch)
    amount = typed_budget(
        provider=launch.ad_account.provider, currency=launch.currency, typed=body.budget
    )
    committed(
        db,
        lambda: google_services.save_google_answers(
            db,
            user=user,
            launch=launch,
            goal=body.goal,
            final_url=body.final_url,
            phone=body.phone,
            area_keys=body.areas,
            country_code=profile.country_code if profile else "",
            daily_budget_minor=amount,
        ),
    )
    return encoded(_common(launch) | {"next": "words"})


@router.get("/launch/{launch_id}/words")
def words(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Step two: keywords and texts, as the AI wrote them and the owner edits."""
    launch = _launch(db, user=user, launch_id=launch_id)
    return encoded(_common(launch) | _words(launch) | {"step": 2})


def _words(launch: GoogleLaunch) -> dict[str, Any]:
    return {
        "keywords": keyword_rows(launch=launch),
        "negative_keywords": list(launch.negative_keywords or []),
        "headlines": list(launch.headlines or []),
        "descriptions": list(launch.descriptions or []),
        "path1": launch.path1,
        "path2": launch.path2,
        "preview": search_preview(launch=launch),
    }


@router.post("/launch/{launch_id}/words")
def save_words(
    launch_id: uuid.UUID, body: WordsIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    launch = _launch(db, user=user, launch_id=launch_id)
    committed(
        db,
        lambda: google_services.save_google_words(
            db,
            user=user,
            launch=launch,
            keywords=body.keywords,
            negative_keywords=body.negative_keywords,
            headlines=body.headlines,
            descriptions=body.descriptions,
            path1=body.path1,
            path2=body.path2,
        ),
    )
    return encoded(_common(launch) | _words(launch))


@router.get("/launch/{launch_id}/review")
def review(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Step three: everything on one page."""
    launch = _launch(db, user=user, launch_id=launch_id)
    return encoded(_common(launch) | _words(launch) | {"step": 3})


@router.post("/launch/{launch_id}/create")
def create(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """«Yaratish»: queue the campaign's creation at Google."""
    launch = _launch(db, user=user, launch_id=launch_id)
    committed(
        db,
        lambda: google_services.request_google_creation(db, user=user, launch=launch),
    )
    return encoded(_common(launch) | _words(launch) | {"step": 3})
