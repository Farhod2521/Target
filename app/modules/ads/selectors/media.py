"""Reads of the creative library: what an advert could be made of, and where it came from."""

import uuid
from dataclasses import dataclass
from typing import Any, Final

from metaads.accounts import ASSET_LIBRARY_URL, media_library_url
from sqlalchemy import ColumnElement, Select, and_, case, false, literal, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import IG_KINDS, MediaKind
from app.modules.ads.models import MediaAsset
from app.modules.integrations.models import AdAccount, PageAccount

ACCOUNT_SOURCE: Final = "account"

PROMOTABLE_KINDS: Final = (
    MediaKind.IMAGE,
    MediaKind.VIDEO,
    MediaKind.IG_IMAGE,
    MediaKind.IG_VIDEO,
)


def media_library_query(
    db: Session,
    *,
    owner: User,
    provider: str,
    ad_account: AdAccount | None = None,
    page: PageAccount | None = None,
    source: str = "",
) -> Select[tuple[MediaAsset]]:
    """Everything this cabinet could put in an ad, Instagram first, newest first."""
    from app.modules.ads.selectors.creatives import video_cover_hashes
    from app.modules.integrations.selectors import active_ad_account, active_page

    account = (
        ad_account if ad_account is not None else active_ad_account(db, owner=owner)
    )
    if account is None:
        return select(MediaAsset).where(false())
    speaking = page if page is not None else active_page(db, owner=owner)
    return (
        select(MediaAsset)
        .where(
            MediaAsset.owner_id == owner.id,
            _reachable_from(db, account=account, page=speaking, source=source),
            MediaAsset.provider == provider,
            MediaAsset.kind.in_(PROMOTABLE_KINDS),
            ~and_(
                MediaAsset.kind == MediaKind.IMAGE,
                MediaAsset.external_id.in_(video_cover_hashes(owner, account)),
            ),
        )
        .order_by(
            case((MediaAsset.kind.in_(IG_KINDS), literal(0)), else_=literal(1)),
            MediaAsset.created_at_provider.desc().nulls_last(),
            MediaAsset.created_at.desc(),
        )
    )


def media_library(
    db: Session,
    *,
    owner: User,
    provider: str,
    ad_account: AdAccount | None = None,
    page: PageAccount | None = None,
    source: str = "",
    kinds: tuple[str, ...] = (),
    limit: int | None = None,
) -> list[MediaAsset]:
    query = media_library_query(
        db,
        owner=owner,
        provider=provider,
        ad_account=ad_account,
        page=page,
        source=source,
    )
    if kinds:
        query = query.where(MediaAsset.kind.in_(kinds))
    if limit is not None:
        query = query.limit(limit)
    return list(db.scalars(query))


def _reachable_from(
    db: Session, *, account: AdAccount, page: PageAccount | None, source: str
) -> ColumnElement[bool]:
    """Which rows this ad account could actually put in an ad."""
    from app.modules.integrations.selectors import chosen_instagram_ids

    if source == ACCOUNT_SOURCE:
        return MediaAsset.ad_account_id == account.id
    if page is None:
        return false() if source else MediaAsset.ad_account_id == account.id
    chosen = chosen_instagram_ids(db, page=page)
    if source:
        instagram_id = _source_instagram(page=page, source=source)
        if instagram_id not in chosen:
            return false()
        return _instagram_rows(page=page, instagram_id=instagram_id)
    return or_(
        MediaAsset.ad_account_id == account.id,
        *(_instagram_rows(page=page, instagram_id=each) for each in chosen),
    )


def _instagram_rows(*, page: PageAccount, instagram_id: str) -> ColumnElement[bool]:
    ids = (
        (instagram_id, "")
        if instagram_id == page.instagram_user_id
        else (instagram_id,)
    )
    return and_(
        MediaAsset.page_id == page.id,
        MediaAsset.kind.in_(IG_KINDS),
        MediaAsset.instagram_user_id.in_(ids),
    )


def post_account(*, asset: MediaAsset, page: PageAccount) -> str:
    """The Instagram account a boosted post has to run as."""
    return asset.instagram_user_id or page.instagram_user_id


def instagram_source(*, page: PageAccount, instagram_id: str) -> str:
    """The chip value for one of the page's accounts."""
    if instagram_id == page.instagram_user_id:
        return str(page.id)
    return f"{page.id}:{instagram_id}"


def _source_instagram(*, page: PageAccount, source: str) -> str:
    if source == str(page.id):
        return page.instagram_user_id
    page_part, _sep, instagram_id = source.partition(":")
    return instagram_id if page_part == str(page.id) else ""


def library_asset(
    db: Session,
    *,
    owner: User,
    provider: str,
    ad_account: AdAccount | None,
    page: PageAccount | None = None,
    asset_id: uuid.UUID,
) -> MediaAsset | None:
    """One row of the grid, for the screen that shows it whole."""
    query = media_library_query(
        db, owner=owner, provider=provider, ad_account=ad_account, page=page
    )
    return db.scalar(query.where(MediaAsset.id == asset_id).limit(1))


def asset_of_kind(
    db: Session, *, owner: User, asset_id: uuid.UUID, kinds: tuple[str, ...]
) -> MediaAsset | None:
    """One library row, if it is a kind an advert can name on its own."""
    return db.scalar(
        select(MediaAsset).where(
            MediaAsset.owner_id == owner.id,
            MediaAsset.id == asset_id,
            MediaAsset.kind.in_(kinds),
        )
    )


@dataclass(frozen=True, slots=True)
class MediaSource:
    """One entry in the picker's source list."""

    value: str
    label: str
    is_instagram: bool


def media_sources(
    db: Session,
    *,
    owner: User,
    account: AdAccount | None,
    page: PageAccount | None = None,
) -> list[MediaSource]:
    """Where this owner's pictures can come from, best first."""
    from app.modules.integrations.selectors import (
        active_page,
        chosen_instagram_ids,
        instagram_handles,
    )

    speaking = page if page is not None else active_page(db, owner=owner)
    sources: list[MediaSource] = []
    if speaking is not None and speaking.owner_id == owner.id:
        handles = instagram_handles(db, page=speaking)
        sources = [
            MediaSource(
                value=instagram_source(page=speaking, instagram_id=instagram_id),
                label=f"@{handles[instagram_id]}"
                if handles.get(instagram_id)
                else speaking.name,
                is_instagram=True,
            )
            for instagram_id in chosen_instagram_ids(db, page=speaking)
        ]
    if account is not None:
        sources.append(
            MediaSource(
                value=ACCOUNT_SOURCE, label="Meta kutubxonasi", is_instagram=False
            )
        )
    return sources


def instagram_source_page(
    db: Session, *, owner: User, page: PageAccount | None, source: str
) -> PageAccount | None:
    """The page whose Instagram the grid is showing, or ``None``."""
    from app.modules.integrations.selectors import active_page, chosen_instagram_ids

    speaking = page if page is not None else active_page(db, owner=owner)
    if (
        speaking is None
        or speaking.owner_id != owner.id
        or _source_instagram(page=speaking, source=source)
        not in chosen_instagram_ids(db, page=speaking)
    ):
        return None
    return speaking


def instagram_connected(
    db: Session, *, owner: User, page: PageAccount | None = None
) -> bool:
    """Whether the page this grid is for reaches an Instagram account."""
    from app.modules.integrations.selectors import active_page

    speaking = page if page is not None else active_page(db, owner=owner)
    return (
        speaking is not None
        and speaking.owner_id == owner.id
        and speaking.has_instagram
    )


@dataclass(frozen=True, slots=True)
class UploadTarget:
    """Where "do it in Meta" sends somebody, and what to call the button."""

    url: str
    is_library: bool


def upload_target(*, ad_account: AdAccount | None) -> UploadTarget:
    if ad_account is None:
        return UploadTarget(url="", is_library=False)
    url = media_library_url(
        ad_account.external_id, business_id=ad_account.business_external_id
    )
    return UploadTarget(url=url, is_library=url.startswith(ASSET_LIBRARY_URL))


def asset_row(asset: MediaAsset) -> dict[str, Any]:
    """One library row as the API hands it over."""
    return {
        "id": str(asset.id),
        "kind": asset.kind,
        "external_id": asset.external_id,
        "name": asset.name,
        "thumbnail_url": asset.thumbnail_url,
        "permalink_url": asset.permalink_url,
        "width": asset.width,
        "height": asset.height,
        "is_eligible": asset.is_eligible,
        "ineligible_reason": asset.ineligible_reason,
    }


__all__ = [
    "ACCOUNT_SOURCE",
    "PROMOTABLE_KINDS",
    "MediaSource",
    "UploadTarget",
    "asset_of_kind",
    "asset_row",
    "instagram_connected",
    "instagram_source",
    "instagram_source_page",
    "library_asset",
    "media_library",
    "media_library_query",
    "media_sources",
    "post_account",
    "upload_target",
]
