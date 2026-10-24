"""Reads about a page beyond the pair: its Instagram, its offer, who holds what."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount, PageAccount, PageInstagram
from app.modules.integrations.selectors.connection import (
    active_page,
    instagram_permission_missing,
    spare_pages,
)


@dataclass(frozen=True, slots=True)
class InstagramProfile:
    page_id: str
    user_id: str
    username: str
    name: str
    biography: str
    website: str
    picture_url: str
    followers: int | None
    follows: int | None
    posts: int | None
    synced_at: datetime | None
    can_refresh: bool

    @property
    def is_read(self) -> bool:
        return self.synced_at is not None


def instagram_profile(
    db: Session, *, owner: User, page: PageAccount | None = None
) -> InstagramProfile | None:
    speaking = page if page is not None else active_page(db, owner=owner)
    if speaking is None or speaking.owner_id != owner.id or not speaking.has_instagram:
        return None
    return InstagramProfile(
        page_id=str(speaking.id),
        user_id=speaking.instagram_user_id,
        username=speaking.instagram_username,
        name=speaking.instagram_name,
        biography=speaking.instagram_biography,
        website=speaking.instagram_website,
        picture_url=speaking.instagram_picture_url,
        followers=speaking.instagram_followers,
        follows=speaking.instagram_follows,
        posts=speaking.instagram_posts,
        synced_at=speaking.instagram_profile_synced_at,
        can_refresh=not instagram_permission_missing(db, owner=owner),
    )


@dataclass(frozen=True, slots=True)
class OfferedPage:
    external_id: str
    name: str
    instagram_username: str

    def __str__(self) -> str:
        return self.name or self.external_id


def pages_on_offer(db: Session, *, owner: User) -> tuple[OfferedPage, ...]:
    return tuple(
        OfferedPage(
            external_id=page.external_id,
            name=page.name,
            instagram_username=page.instagram_username,
        )
        for page in spare_pages(db, owner=owner)
    )


def ad_accounts_of_other_owners(
    db: Session, *, owner: User, provider: str, external_ids: Iterable[str]
) -> set[str]:
    ids = list(external_ids)
    if not ids:
        return set()
    return set(
        db.scalars(
            select(AdAccount.external_id).where(
                AdAccount.provider == provider,
                AdAccount.external_id.in_(ids),
                AdAccount.owner_id != owner.id,
            )
        )
    )


@dataclass(frozen=True, slots=True)
class InstagramChoice:
    instagram_user_id: str
    username: str
    is_page_own: bool
    is_active: bool
    is_linked: bool


def chosen_instagram_ids(db: Session, *, page: PageAccount) -> list[str]:
    ids = [page.instagram_user_id] if page.instagram_user_id else []
    if not page.is_active:
        return ids
    extras = db.scalars(
        select(PageInstagram.instagram_user_id)
        .where(
            PageInstagram.page_id == page.id,
            PageInstagram.is_active.is_(True),
            PageInstagram.is_linked.is_(True),
            PageInstagram.instagram_user_id != page.instagram_user_id,
        )
        .order_by(PageInstagram.username)
    )
    return ids + [found for found in extras if found not in ids]


def instagram_choices(db: Session, *, page: PageAccount) -> list[InstagramChoice]:
    rows = db.scalars(
        select(PageInstagram)
        .where(
            PageInstagram.page_id == page.id,
            or_(PageInstagram.is_linked.is_(True), PageInstagram.is_active.is_(True)),
        )
        .order_by(PageInstagram.username)
    )
    choices = [
        InstagramChoice(
            instagram_user_id=row.instagram_user_id,
            username=row.username,
            is_page_own=row.instagram_user_id == page.instagram_user_id,
            is_active=row.is_active,
            is_linked=row.is_linked,
        )
        for row in rows
    ]
    return sorted(choices, key=lambda choice: not choice.is_page_own)


def instagram_handles(db: Session, *, page: PageAccount) -> dict[str, str]:
    found = {
        user_id: username
        for user_id, username in db.execute(
            select(PageInstagram.instagram_user_id, PageInstagram.username).where(
                PageInstagram.page_id == page.id
            )
        )
    }
    if page.instagram_user_id:
        found[page.instagram_user_id] = page.instagram_username
    return found
