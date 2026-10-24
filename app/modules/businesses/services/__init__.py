import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.presets import categories, fallback_category
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.businesses.constants import CATEGORY_TRANSLATIONS
from app.modules.businesses.models import Business, BusinessCategory, CustomCategory
from app.modules.businesses.selectors import business_for, google_profile
from app.modules.integrations.models import AdAccount, PageAccount

logger = logging.getLogger(__name__)

PROFILE_FIELDS = (
    "name",
    "category",
    "timezone",
    "country_code",
    "city",
    "contact_phone",
    "website",
    "offer_text",
    "working_hours",
)
COPIED = (
    "name",
    "category",
    "direction_id",
    "custom_category_id",
    "timezone",
    "country_code",
    "city",
    "lat",
    "lng",
    "contact_phone",
    "website",
    "offer_text",
    "working_hours",
)


def save_profile(
    db: Session,
    *,
    user: User,
    page: PageAccount | None = None,
    ad_account: AdAccount | None = None,
    direction: BusinessCategory | None = None,
    custom_label: str = "",
    **fields: Any,
) -> Business:
    business = db.scalar(
        select(Business).where(
            Business.user_id == user.id,
            Business.page_id == page.id if page else Business.page_id.is_(None),
            Business.ad_account_id == ad_account.id
            if ad_account
            else Business.ad_account_id.is_(None),
        )
    )
    custom = _category_row(db, user=user, label=custom_label)
    created = business is None
    if business is None:
        business = Business(
            user_id=user.id,
            page_id=page.id if page else None,
            ad_account_id=ad_account.id if ad_account else None,
            **_from_page(page),
        )
        db.add(business)
    for name, value in fields.items():
        setattr(business, name, value)
    business.direction_id = direction.id if direction else None
    business.custom_category_id = custom.id if custom else None
    business.updated_at = utcnow()
    db.flush()
    if created:
        emit(
            db,
            owner_id=user.id,
            name=EventName.BUSINESS_CREATED,
            aggregate_type="business",
            aggregate_id=business.id,
            payload={
                "name": business.name,
                "country_code": business.country_code,
                "timezone": business.timezone,
                "page": str(page.id) if page is not None else "",
                "ad_account": str(ad_account.id) if ad_account is not None else "",
            },
        )
    db.commit()
    return business


def _from_page(page: PageAccount | None) -> dict[str, object]:
    if page is None:
        return {}
    seeded: dict[str, object] = {}
    if page.location_city:
        seeded["city"] = page.location_city
    if page.has_pin:
        seeded["lat"] = page.location_lat
        seeded["lng"] = page.location_lng
    return seeded


def _category_row(db: Session, *, user: User, label: str) -> CustomCategory | None:
    if not label:
        return None
    row = db.scalar(
        select(CustomCategory).where(
            CustomCategory.owner_id == user.id, CustomCategory.label == label
        )
    )
    if row is None:
        row = CustomCategory(
            owner_id=user.id, label=label, preset_key=fallback_category()
        )
        db.add(row)
        db.flush()
    return row


def adopt_page(db: Session, *, user: User, page: PageAccount) -> Business | None:
    if db.scalar(
        select(Business.id).where(
            Business.user_id == user.id, Business.page_id == page.id
        )
    ):
        return None
    orphan = db.scalar(
        select(Business)
        .where(
            Business.user_id == user.id,
            Business.page_id.is_(None),
            Business.ad_account_id.is_(None),
        )
        .limit(1)
    )
    if orphan is None:
        return None
    orphan.page_id = page.id
    orphan.updated_at = utcnow()
    db.flush()
    logger.info("profile %s now describes page %s", orphan.id, page.id)
    return orphan


def adopt_directions(db: Session) -> int:
    by_key = {row.key: row for row in db.scalars(select(BusinessCategory))}
    adopted = 0
    for business in db.scalars(
        select(Business).where(
            Business.direction_id.is_(None), Business.custom_category_id.is_(None)
        )
    ):
        row = by_key.get(business.category)
        if row is None:
            continue
        business.direction_id = row.id
        adopted += 1
    db.commit()
    return adopted


def remember_location(
    db: Session, *, business: Business, lat: str = "", lng: str = "", city: str = ""
) -> bool:
    fields: dict[str, object] = {}
    if city and not business.city:
        fields["city"] = city[:128]
    if business.lat is None and business.lng is None:
        point = _point(lat=lat, lng=lng)
        if point is not None:
            fields["lat"], fields["lng"] = point
    if not fields:
        return False
    for name, value in fields.items():
        setattr(business, name, value)
    business.updated_at = utcnow()
    db.flush()
    logger.info("profile %s learned where it is", business.id)
    return True


def _point(*, lat: str, lng: str) -> tuple[Decimal, Decimal] | None:
    if not (lat and lng):
        return None
    try:
        return Decimal(lat), Decimal(lng)
    except (InvalidOperation, ValueError):
        logger.warning("a pin arrived that is not a pair of numbers")
        return None


def seed_google_profile(
    db: Session, *, user: User, account: AdAccount
) -> Business | None:
    if google_profile(db, owner=user, account=account) is not None:
        return None
    source = business_for(db, user)
    if source is None:
        return None
    copy = Business(
        user_id=user.id,
        ad_account_id=account.id,
        **{field: getattr(source, field) for field in COPIED},
    )
    db.add(copy)
    db.flush()
    emit(
        db,
        owner_id=user.id,
        name=EventName.BUSINESS_CREATED,
        aggregate_type="business",
        aggregate_id=copy.id,
        payload={
            "name": copy.name,
            "country_code": copy.country_code,
            "timezone": copy.timezone,
            "page": "",
            "ad_account": str(account.id),
        },
    )
    logger.info(
        "google account %s profile copied from business %s", account.id, source.id
    )
    return copy


@dataclass(frozen=True, slots=True)
class SyncResult:
    created: int
    total: int


def sync_categories(db: Session) -> SyncResult:
    known = set(db.scalars(select(BusinessCategory.key)))
    created = 0
    for position, category in enumerate(categories()):
        if category.key in known:
            continue
        russian, english = CATEGORY_TRANSLATIONS.get(
            category.key, (category.label, category.label)
        )
        db.add(
            BusinessCategory(
                key=category.key,
                label_uz=category.label,
                label_ru=russian,
                label_en=english,
                preset_key=category.key,
                position=position,
            )
        )
        created += 1
    db.commit()
    total = len(list(db.scalars(select(BusinessCategory.id))))
    return SyncResult(created=created, total=total)


__all__ = [
    "PROFILE_FIELDS",
    "SyncResult",
    "adopt_directions",
    "adopt_page",
    "remember_location",
    "save_profile",
    "seed_google_profile",
    "sync_categories",
]
