"""The Google Ads screen and its Search wizard.

Everything here is not found for an owner Google Ads is not switched on
for, except the screen, which answers ``null``. ``/screen`` lists one
account's campaigns for a period in the cabinet's shape; a press
(``/switch``, ``/budget``, ``/delete``, ``/refresh``, ``/account``) is queued
and answers a sentence, and the screen read again shows where it got to.

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
from app.common.contract import Camel, Money
from app.common.exceptions import NotFound
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads import actions
from app.modules.ads.constants import (
    GOOGLE_FAILURES,
    GOOGLE_GOAL_LABELS,
    GoogleGoal,
    ManagedLevel,
)
from app.modules.ads.contract.google import GoogleScreenAnswer, screen_of
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
from app.modules.integrations.selectors.google import (
    current_google_account,
    google_ads_on,
)
from app.modules.integrations.services import select_google_account

router = APIRouter(prefix="/google", tags=["google ads"])
LEVELS = frozenset({ManagedLevel.CAMPAIGN, ManagedLevel.ADSET})


class SwitchIn(Camel):
    level: Literal["campaign", "adset"]
    id: str
    wanted: Literal["pause", "resume"]


class GoogleBudgetIn(Camel):
    id: str
    budget: Money


class GoogleIdIn(Camel):
    id: str


class Said(Camel):
    message: str


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


def switched_on(user: User) -> None:
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


@router.get("/screen", response_model=GoogleScreenAnswer)
def screen(
    db: Db, user: CurrentUser, period: str = Query(DEFAULT_PERIOD)
) -> GoogleScreenAnswer:
    """One account's campaigns and groups; null without a Google Ads account here."""
    found = (
        google_screen(
            db, owner=user, period=period if period in PERIODS else DEFAULT_PERIOD
        )
        if google_ads_on(user=user)
        else None
    )
    return GoogleScreenAnswer(screen=screen_of(found) if found is not None else None)


@router.post("/switch", response_model=Said)
def switch(body: SwitchIn, db: Db, user: CurrentUser) -> Said:
    """Stop or start one campaign or group."""
    switched_on(user)
    kind = actions.Pause if body.wanted == "pause" else actions.Resume
    ask = kind(level=body.level, external_id=body.id)
    committed(db, lambda: actions.request(db, user=user, ask=ask))
    return Said(message="Google'ga yuborildi. Holat bir necha soniyada yangilanadi.")


@router.post("/budget", response_model=Said)
def budget(body: GoogleBudgetIn, db: Db, user: CurrentUser) -> Said:
    """A campaign's daily figure. Google keeps a budget on campaigns only."""
    switched_on(user)
    account = current_google_account(db, owner=user)
    if account is None:
        raise NotFound("Google Ads akkaunti ulanmagan.")
    amount = typed_budget(
        provider=account.provider,
        currency=account.currency,
        typed=str(Decimal(body.budget.minor).scaleb(-body.budget.exponent)),
    )
    committed(
        db,
        lambda: actions.request(
            db,
            user=user,
            ask=actions.Budget(
                level=ManagedLevel.CAMPAIGN,
                external_id=body.id,
                daily_budget_minor=amount,
            ),
        ),
    )
    return Said(message="Google'ga yuborildi. Byudjet tez orada yangilanadi.")


@router.post("/delete", response_model=Said)
def delete(body: GoogleIdIn, db: Db, user: CurrentUser) -> Said:
    """Remove a campaign for good, after the dialog has asked."""
    switched_on(user)
    ask = actions.Delete(level=ManagedLevel.CAMPAIGN, external_id=body.id)
    committed(db, lambda: actions.request(db, user=user, ask=ask))
    return Said(message="Google'ga yuborildi. Kampaniya o'chiriladi.")


@router.post("/refresh", response_model=Said)
def refresh(db: Db, user: CurrentUser) -> Said:
    """Read the account from Google again."""
    switched_on(user)
    committed(db, lambda: google_services.request_google_refresh(db, user=user))
    return Said(message="Yangilanmoqda. Bir daqiqada tayyor bo'ladi.")


@router.post("/account", response_model=Said)
def account(body: GoogleIdIn, db: Db, user: CurrentUser) -> Said:
    """Which of the subscription's Google Ads accounts the screen shows."""
    switched_on(user)
    chosen = select_google_account(db, user=user, external_id=body.id)
    db.commit()
    return Said(message="Google Ads akkaunti tanlandi: %(name)s" % {"name": chosen})


# -- the Search wizard -----------------------------------------------------------------


def google_launch(db: Session, *, user: User, launch_id: uuid.UUID) -> GoogleLaunch:
    switched_on(user)
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
    switched_on(user)
    launch = committed(db, lambda: google_services.start_google_launch(db, user=user))
    return encoded(_common(launch))


@router.get("/launch/{launch_id}/answers")
def answers(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Step one: goal, site, phone, places, budget."""
    launch = google_launch(db, user=user, launch_id=launch_id)
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
    launch = google_launch(db, user=user, launch_id=launch_id)
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
    launch = google_launch(db, user=user, launch_id=launch_id)
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
    launch = google_launch(db, user=user, launch_id=launch_id)
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
    launch = google_launch(db, user=user, launch_id=launch_id)
    return encoded(_common(launch) | _words(launch) | {"step": 3})


@router.post("/launch/{launch_id}/create")
def create(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """«Yaratish»: queue the campaign's creation at Google."""
    launch = google_launch(db, user=user, launch_id=launch_id)
    committed(
        db,
        lambda: google_services.request_google_creation(db, user=user, launch=launch),
    )
    return encoded(_common(launch) | _words(launch) | {"step": 3})
