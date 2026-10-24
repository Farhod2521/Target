import uuid

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.common.presets import label_for
from app.modules.accounts.models import User
from app.modules.businesses.models import Business, BusinessCategory
from app.modules.integrations.models import AdAccount, PageAccount


def _rows() -> Select[tuple[Business]]:
    return select(Business).where(Business.ad_account_id.is_(None))


def business_for(db: Session, user: User) -> Business | None:
    current = db.scalar(
        _rows()
        .join(PageAccount, PageAccount.id == Business.page_id)
        .where(Business.user_id == user.id, PageAccount.is_current.is_(True))
        .limit(1)
    )
    if current is not None:
        return current
    return db.scalar(
        _rows().where(Business.user_id == user.id, Business.page_id.is_(None)).limit(1)
    )


def business_for_page(
    db: Session, *, owner: User, page: PageAccount | None
) -> Business | None:
    if page is None:
        return business_for(db, owner)
    named = db.scalar(
        _rows().where(Business.user_id == owner.id, Business.page_id == page.id)
    )
    if named is not None:
        return named
    return db.scalar(
        _rows().where(Business.user_id == owner.id, Business.page_id.is_(None)).limit(1)
    )


def business_for_page_id(db: Session, *, owner: User, page_id: str) -> Business | None:
    if not page_id:
        return business_for(db, owner)
    page = db.scalar(
        select(PageAccount).where(
            PageAccount.owner_id == owner.id, PageAccount.external_id == page_id
        )
    )
    return business_for_page(db, owner=owner, page=page) if page is not None else None


def page_profile(db: Session, *, owner: User, page: PageAccount) -> Business | None:
    return db.scalar(
        _rows().where(Business.user_id == owner.id, Business.page_id == page.id)
    )


def businesses_for(db: Session, *, owner: User) -> list[Business]:
    return list(
        db.scalars(
            _rows()
            .outerjoin(PageAccount, PageAccount.id == Business.page_id)
            .where(Business.user_id == owner.id)
            .order_by(PageAccount.is_current.desc().nulls_last(), Business.name)
        )
    )


def profiles_by_page(db: Session, *, owner: User) -> dict[uuid.UUID, Business]:
    return {
        business.page_id: business
        for business in db.scalars(
            _rows().where(Business.user_id == owner.id, Business.page_id.is_not(None))
        )
        if business.page_id is not None
    }


def google_profile(db: Session, *, owner: User, account: AdAccount) -> Business | None:
    return db.scalar(
        select(Business).where(
            Business.user_id == owner.id, Business.ad_account_id == account.id
        )
    )


def category_label(business: Business) -> str:
    if business.custom_category_id is not None and business.custom_category:
        return business.custom_category.label
    if business.direction_id is not None and business.direction:
        return business.direction.label
    return label_for(category=business.category)


def business_timezone(db: Session, *, owner: User) -> str:
    return (
        db.scalar(
            select(Business.timezone)
            .outerjoin(PageAccount, PageAccount.id == Business.page_id)
            .where(
                Business.user_id == owner.id,
                Business.ad_account_id.is_(None),
                or_(PageAccount.is_current.is_(True), Business.page_id.is_(None)),
            )
            .order_by(PageAccount.is_current.desc().nulls_last())
            .limit(1)
        )
        or ""
    )


def public_business(db: Session, *, business_id: uuid.UUID) -> Business | None:
    return db.get(Business, business_id)


def offered_directions(db: Session) -> list[BusinessCategory]:
    return list(
        db.scalars(
            select(BusinessCategory)
            .where(BusinessCategory.is_active.is_(True))
            .order_by(BusinessCategory.position, BusinessCategory.key)
        )
    )


def direction_choices(db: Session) -> list[tuple[str, str]]:
    return [(row.key, row.label) for row in offered_directions(db)]


def direction_by_key(db: Session, key: str) -> BusinessCategory | None:
    if not key:
        return None
    return db.scalar(select(BusinessCategory).where(BusinessCategory.key == key))


__all__ = [
    "business_for",
    "business_for_page",
    "business_for_page_id",
    "business_timezone",
    "businesses_for",
    "category_label",
    "direction_by_key",
    "direction_choices",
    "google_profile",
    "offered_directions",
    "page_profile",
    "profiles_by_page",
    "public_business",
]
