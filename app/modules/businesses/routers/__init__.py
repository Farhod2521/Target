import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common import throttle
from app.common.catalogs import COUNTRIES, timezone_choices
from app.common.config import settings
from app.common.presets import fallback_category
from app.modules.accounts.models import User
from app.modules.businesses import selectors, services
from app.modules.businesses.models import Business
from app.modules.businesses.schemas import (
    CUSTOM,
    BusinessOut,
    BusinessPlaceOut,
    ChoiceOut,
    ProfileChoices,
    ProfileForm,
    ProfileIn,
)
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.integrations.selectors import (
    active_page,
    page_by_id,
    subscribed_google_account,
)

router = APIRouter(prefix="/business", tags=["business"])
# As the launch editor's own place search: as long a word, as often.
MAX_PLACE_SEARCH = 100
PLACE_SEARCH_BUCKET = "geo-search"
PLACE_SEARCHES_PER_MINUTE = 60


def _out(business: Business | None) -> BusinessOut | None:
    if business is None:
        return None
    out = BusinessOut.model_validate(business)
    out.category_label = selectors.category_label(business)
    out.direction_key = business.direction.key if business.direction else ""
    out.custom_label = (
        business.custom_category.label if business.custom_category else ""
    )
    return out


def _form(business: Business | None, *, name: str) -> ProfileForm:
    defaults = settings.profile_defaults if business is None else {}
    return ProfileForm(
        business=_out(business),
        initial_name=name if business is None else "",
        initial_country_code=defaults.get("country_code", ""),
        initial_timezone=defaults.get("timezone", ""),
    )


def _cleaned(
    db: Session,
    body: ProfileIn,
    *,
    saved: Business | None,
    user: User,
    google: bool = False,
) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True, exclude={"category", "custom_label"})
    if "website" in data:
        data["website"] = str(data["website"])
    if "regions" in data:
        data["regions"] = _regions(
            db, user, data["regions"], saved=saved, google=google
        )
    if body.category != CUSTOM:
        direction = selectors.direction_by_key(db, body.category)
        offered = direction is not None and (
            direction.is_active
            or (saved is not None and saved.direction_id == direction.id)
        )
        if not offered or direction is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Yo'nalishni ro'yxatdan tanlang.",
            )
        return data | {
            "category": direction.preset_key,
            "direction": direction,
            "custom_label": "",
        }
    label = body.custom_label.strip()
    if not label:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Yo'nalishingizni yozing yoki ro'yxatdan tanlang.",
        )
    return data | {
        "category": fallback_category(),
        "direction": None,
        "custom_label": label,
    }


def _regions(
    db: Session,
    user: User,
    picked: list[dict[str, str]],
    *,
    saved: Business | None,
    google: bool,
) -> list[dict[str, str]]:
    """The places as the search offers them; one already kept is not asked again.

    A key from the browser reaches a launch's targeting only after the
    provider has answered it under that name, as the launch editor does.
    """
    if picked and google:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Google profilida hudud hozircha tanlanmaydi.",
        )
    from app.modules.ads.services.locations import confirmed_for_owner

    kept = {row["key"]: row for row in (saved.regions if saved else []) or []}
    unique = list({row["key"]: row for row in picked}.values())
    fresh = [row for row in unique if row["key"] not in kept]
    found = confirmed_for_owner(db, owner=user, picked=fresh) if fresh else []
    if found is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Joylardan birini qidiruvdan qayta tanlang.",
        )
    confirmed = {row["key"]: row for row in found}
    return [kept.get(row["key"]) or confirmed[row["key"]] for row in unique]


def _page(db: Session, user: User, page_id: uuid.UUID) -> PageAccount:
    page = page_by_id(db, owner=user, page_id=page_id)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sahifa topilmadi.")
    return page


def _google(db: Session, user: User, account_id: uuid.UUID) -> AdAccount:
    account = subscribed_google_account(db, owner=user, account_id=account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Akkaunt topilmadi.")
    return account


@router.get("/choices", response_model=ProfileChoices)
def choices(db: Db, user: CurrentUser) -> ProfileChoices:
    return ProfileChoices(
        categories=[
            ChoiceOut(value=key, label=label)
            for key, label in selectors.direction_choices(db)
        ],
        countries=[
            ChoiceOut(value=code, label=name)
            for code, name in sorted(COUNTRIES, key=lambda pair: pair[1])
        ],
        timezones=[ChoiceOut(value=z, label=label) for z, label in timezone_choices()],
    )


@router.get("/locations", response_model=list[BusinessPlaceOut])
def locations(
    db: Db,
    user: CurrentUser,
    q: str = Query("", max_length=MAX_PLACE_SEARCH),
    country: str = Query("", pattern="^([A-Za-z]{2})?$"),
) -> list[BusinessPlaceOut]:
    """Where the business works: the place search, the given country's rows first."""
    from app.modules.ads.services.locations import owner_places, place_query

    query = place_query(q)
    if not query:
        return []
    if not throttle.hit(
        bucket=PLACE_SEARCH_BUCKET,
        key=str(user.id),
        limit=PLACE_SEARCHES_PER_MINUTE,
        window_seconds=60,
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
        )
    business = selectors.business_for(db, user)
    rows = owner_places(
        db,
        owner=user,
        query=query,
        country_code=country or (business.country_code if business else ""),
    )
    return [
        BusinessPlaceOut(
            id=row["key"],
            name=row["name"],
            type=row["kind"],
            context=row["context"],
            country_code=row["country_code"],
        )
        for row in rows
    ]


@router.get("", response_model=ProfileForm)
def profile(db: Db, user: CurrentUser) -> ProfileForm:
    business = selectors.business_for(db, user)
    page = active_page(db, owner=user)
    return _form(business, name=page.name if page else "")


@router.put("", response_model=BusinessOut)
def save(body: ProfileIn, db: Db, user: CurrentUser) -> BusinessOut | None:
    saved = selectors.business_for(db, user)
    business = services.save_profile(
        db,
        user=user,
        page=active_page(db, owner=user),
        **_cleaned(db, body, saved=saved, user=user),
    )
    return _out(business)


@router.get("/pages/{page_id}", response_model=ProfileForm)
def page_profile(page_id: uuid.UUID, db: Db, user: CurrentUser) -> ProfileForm:
    page = _page(db, user, page_id)
    return _form(selectors.page_profile(db, owner=user, page=page), name=page.name)


@router.put("/pages/{page_id}", response_model=BusinessOut)
def save_page_profile(
    page_id: uuid.UUID, body: ProfileIn, db: Db, user: CurrentUser
) -> BusinessOut | None:
    page = _page(db, user, page_id)
    saved = selectors.page_profile(db, owner=user, page=page)
    business = services.save_profile(
        db, user=user, page=page, **_cleaned(db, body, saved=saved, user=user)
    )
    return _out(business)


@router.get("/google/{account_id}", response_model=ProfileForm)
def google_profile(account_id: uuid.UUID, db: Db, user: CurrentUser) -> ProfileForm:
    account = _google(db, user, account_id)
    return _form(
        selectors.google_profile(db, owner=user, account=account), name=account.name
    )


@router.put("/google/{account_id}", response_model=BusinessOut)
def save_google_profile(
    account_id: uuid.UUID, body: ProfileIn, db: Db, user: CurrentUser
) -> BusinessOut | None:
    account = _google(db, user, account_id)
    saved = selectors.google_profile(db, owner=user, account=account)
    business = services.save_profile(
        db,
        user=user,
        ad_account=account,
        **_cleaned(db, body, saved=saved, user=user, google=True),
    )
    return _out(business)
