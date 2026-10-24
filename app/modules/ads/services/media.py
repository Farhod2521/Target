"""The media library: an ad account's images and videos, a page's posts and
its Instagram media, read from Meta and kept as MediaAsset rows."""

import logging
import unicodedata
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Final

from metaads import PROVIDER
from metaads.creatives import (
    list_instagram_media,
    list_media,
    list_promotable_posts,
    list_recent_instagram_media,
)
from metaads.dto import MediaDTO
from metaads.errors import MetaError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DatabaseError, DataError
from sqlalchemy.orm import Session

from app.common import throttle
from app.common.crypto import decrypt
from app.common.db import on_commit, utcnow
from app.common.exceptions import DecryptionFailed
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    IG_KINDS,
    MEDIA_RECENT_STALE_SECONDS,
    MEDIA_REFRESH_SECONDS,
    MEDIA_STALE_SECONDS,
    REFRESH_QUEUE,
    LaunchStatus,
    MediaKind,
)
from app.modules.ads.exceptions import MediaAskedRecently
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount, PageAccount

logger = logging.getLogger(__name__)
ACCOUNT_KINDS: tuple[str, ...] = (MediaKind.IMAGE, MediaKind.VIDEO)
REFRESH_BUCKET = "ads:media"
OPEN_BUCKET = "ads:media-open"
RECENT_BUCKET = "ads:media-recent"
REFRESH_LIMIT = 1
_OPEN_LAUNCHES: Final = (
    LaunchStatus.DRAFT,
    LaunchStatus.BUILDING,
    LaunchStatus.READY,
    LaunchStatus.FAILED,
    LaunchStatus.ROLLED_BACK,
)


def same_words(first: str, second: str) -> bool:
    return _plain(first) == _plain(second)


def _plain(text: str) -> str:
    joined = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    lines = joined.replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


# -- reading the library --------------------------------------------------------------


def sync_media(db: Session, *, ad_account_id: uuid.UUID | str) -> str:
    account = db.scalars(
        select(AdAccount).where(
            AdAccount.id == uuid.UUID(str(ad_account_id)),
            AdAccount.provider == PROVIDER,
        )
    ).first()
    if account is None:
        return "gone"
    token = _token(account)
    if token is None:
        return "unusable"
    read_at = utcnow()
    assets = _read(
        lambda: list_media(account_id=account.external_id, token=token),
        what="media list",
        subject=account.external_id,
    )
    stored = assets is not None and _store_account(
        db, account=account, assets=assets, read_at=read_at
    )
    pages = _page_library(db, account.owner)
    if assets is not None:
        account.media_synced_at = utcnow()
        db.commit()
    if assets is None or not stored:
        return f"failed+{pages}"
    return str(len(assets) + pages)


def sync_owner_media(db: Session, *, owner_id: uuid.UUID | str) -> str:
    owner = db.get(User, uuid.UUID(str(owner_id)))
    if owner is None:
        return "gone"
    return str(_page_library(db, owner))


def _store_account(
    db: Session, *, account: AdAccount, assets: list[MediaDTO], read_at: datetime
) -> bool:
    try:
        _store(
            db,
            owner=account.owner,
            ad_account=account,
            page=None,
            kinds=ACCOUNT_KINDS,
            assets=assets,
            read_at=read_at,
        )
    except DatabaseError:
        db.rollback()
        logger.exception(
            "media library not stored", extra={"account": account.external_id}
        )
        return False
    return True


def _page_library(db: Session, owner: User) -> int:
    counted = 0
    pages = db.scalars(
        select(PageAccount).where(
            PageAccount.owner_id == owner.id, PageAccount.provider == PROVIDER
        )
    ).all()
    for page in pages:
        if not page.is_active:
            continue
        try:
            token = decrypt(page.token_encrypted)
        except DecryptionFailed:
            logger.exception("page %s could not be decrypted", page.id)
            continue
        counted += _page_posts(db, owner=owner, page=page, token=token)
        counted += _instagram_library(db, owner=owner, page=page, token=token)
    return counted


def _page_posts(db: Session, *, owner: User, page: PageAccount, token: str) -> int:
    read_at = utcnow()
    posts = _read(
        lambda: list_promotable_posts(page_id=page.external_id, token=token),
        what="post list",
        subject=page.external_id,
    )
    if posts is None:
        return 0
    _store(
        db,
        owner=owner,
        ad_account=None,
        page=page,
        kinds=(MediaKind.POST,),
        assets=posts,
        read_at=read_at,
    )
    return len(posts)


def _instagram_library(
    db: Session, *, owner: User, page: PageAccount, token: str
) -> int:
    from app.modules.integrations.selectors import chosen_instagram_ids
    from app.modules.integrations.services import sync_instagram_profile

    if not page.instagram_user_id:
        logger.info(
            "instagram not linked", extra={"page": page.external_id, "media": 0}
        )
        return 0
    sync_instagram_profile(db, page=page, token=token)
    counted = 0
    for instagram_id in chosen_instagram_ids(db, page=page):
        counted += _instagram_account(
            db, owner=owner, page=page, token=token, instagram_id=instagram_id
        )
    page.instagram_media_synced_at = utcnow()
    db.commit()
    return counted


def _instagram_account(
    db: Session, *, owner: User, page: PageAccount, token: str, instagram_id: str
) -> int:
    read_at = utcnow()
    media = _read(
        lambda: list_instagram_media(ig_user_id=instagram_id, token=token),
        what="instagram media",
        subject=instagram_id,
    )
    if media is None:
        logger.info(
            "instagram media unread",
            extra={"page": page.external_id, "instagram": instagram_id},
        )
        return 0
    _store(
        db,
        owner=owner,
        ad_account=None,
        page=page,
        kinds=IG_KINDS,
        assets=media,
        read_at=read_at,
        instagram_user_id=instagram_id,
    )
    logger.info(
        "instagram media read",
        extra={
            "page": page.external_id,
            "instagram": instagram_id,
            "media": len(media),
            "blocked": sum(1 for item in media if item.is_eligible is False),
        },
    )
    return len(media)


def _read(
    call: Callable[[], list[MediaDTO]], *, what: str, subject: str
) -> list[MediaDTO] | None:
    try:
        return call()
    except MetaError as exc:
        logger.info("%s failed for %s: %s", what, subject, exc)
        return None


def _token(account: AdAccount) -> str | None:
    connection = account.connection
    if connection is None or connection.status not in USABLE_CONNECTION_STATUSES:
        return None
    try:
        return decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", connection.id)
        return None


def _store(
    db: Session,
    *,
    owner: User,
    ad_account: AdAccount | None,
    page: PageAccount | None,
    kinds: tuple[str, ...],
    assets: list[MediaDTO],
    read_at: datetime,
    instagram_user_id: str = "",
) -> None:
    seen = upsert_media(
        db,
        owner=owner,
        ad_account=ad_account,
        page=page,
        kinds=kinds,
        assets=assets,
        instagram_user_id=instagram_user_id,
    )
    scope = (
        [MediaAsset.page_id == page.id]
        if page
        else [MediaAsset.ad_account_id == ad_account.id]
    )  # type: ignore[union-attr]
    if page and instagram_user_id:
        own = instagram_user_id == page.instagram_user_id
        scope.append(
            MediaAsset.instagram_user_id.in_(
                (instagram_user_id, "") if own else (instagram_user_id,)
            )
        )
    db.execute(
        delete(MediaAsset)
        .where(
            MediaAsset.owner_id == owner.id,
            MediaAsset.provider == PROVIDER,
            MediaAsset.kind.in_([str(k) for k in kinds]),
            MediaAsset.created_at < read_at,
            MediaAsset.external_id.not_in(seen),
            *scope,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()


def upsert_media(
    db: Session,
    *,
    owner: User,
    ad_account: AdAccount | None,
    page: PageAccount | None,
    kinds: tuple[str, ...],
    assets: list[MediaDTO],
    instagram_user_id: str = "",
) -> list[str]:
    now = utcnow()
    seen: list[str] = []
    captions = _captions(db, owner=owner, kinds=kinds)
    for asset in assets:
        if not asset.external_id:
            continue
        seen.append(asset.external_id)
        _write(
            db,
            owner=owner,
            ad_account=ad_account,
            page=page,
            asset=asset,
            now=now,
            instagram_user_id=instagram_user_id,
        )
    if captions:
        follow_captions(
            db,
            owner=owner,
            before=captions,
            after={
                asset.external_id: asset.name
                for asset in assets
                if asset.kind in IG_KINDS
            },
        )
    return seen


def _captions(db: Session, *, owner: User, kinds: tuple[str, ...]) -> dict[str, str]:
    asked = [str(kind) for kind in kinds if kind in IG_KINDS]
    if not asked:
        return {}
    return dict(
        db.execute(
            select(MediaAsset.external_id, MediaAsset.name).where(
                MediaAsset.owner_id == owner.id,
                MediaAsset.provider == PROVIDER,
                MediaAsset.kind.in_(asked),
            )
        ).all()
    )


def _write(
    db: Session,
    *,
    owner: User,
    ad_account: AdAccount | None,
    page: PageAccount | None,
    asset: MediaDTO,
    now: datetime,
    instagram_user_id: str = "",
) -> None:
    fields = {
        "ad_account_id": ad_account.id if ad_account else None,
        "page_id": page.id if page else None,
        "name": asset.name,
        "thumbnail_url": asset.thumbnail_url,
        "permalink_url": asset.permalink_url,
        "width": asset.width,
        "height": asset.height,
        "is_eligible": asset.is_eligible,
        "ineligible_reason": asset.ineligible_reason,
        "synced_at": now,
    }
    if instagram_user_id:
        fields["instagram_user_id"] = instagram_user_id
    if asset.created_time is not None:
        fields["created_at_provider"] = asset.created_time
    try:
        with db.begin_nested():
            row = db.scalars(
                select(MediaAsset).where(
                    MediaAsset.owner_id == owner.id,
                    MediaAsset.provider == PROVIDER,
                    MediaAsset.kind == str(asset.kind),
                    MediaAsset.external_id == asset.external_id,
                )
            ).first()
            if row is None:
                row = MediaAsset(
                    owner_id=owner.id,
                    provider=PROVIDER,
                    kind=str(asset.kind),
                    external_id=asset.external_id,
                )
                db.add(row)
            for key, value in fields.items():
                setattr(row, key, value)
            db.flush()
    except DataError:
        logger.warning(
            "media row refused by the database",
            extra={
                "asset": asset.external_id,
                "kind": asset.kind,
                "name_length": len(asset.name),
                "thumbnail_length": len(asset.thumbnail_url),
                "permalink_length": len(asset.permalink_url),
                "reason_length": len(asset.ineligible_reason),
            },
        )


def follow_captions(
    db: Session, *, owner: User, before: dict[str, str], after: dict[str, str]
) -> int:
    """Carry a changed Instagram caption into drafts that still quote the old one."""
    changed = {
        media_id: text
        for media_id, text in after.items()
        if media_id in before and not same_words(before[media_id], text)
    }
    if not changed:
        return 0
    rows = db.scalars(
        select(LaunchCreative)
        .join(MediaAsset, MediaAsset.id == LaunchCreative.media_asset_id)
        .join(CampaignLaunch, CampaignLaunch.id == LaunchCreative.launch_id)
        .where(
            LaunchCreative.owner_id == owner.id,
            MediaAsset.external_id.in_(list(changed)),
            MediaAsset.kind.in_([str(k) for k in IG_KINDS]),
            CampaignLaunch.status.in_([str(s) for s in _OPEN_LAUNCHES]),
            LaunchCreative.headline == "",
            LaunchCreative.description == "",
        )
    )
    moved = 0
    for row in rows:
        media_id = row.media_asset.external_id if row.media_asset else ""
        if media_id not in changed or not same_words(
            row.primary_text, before[media_id]
        ):
            continue
        row.primary_text = changed[media_id]
        moved += 1
    db.flush()
    return moved


def sync_recent_instagram(db: Session, *, page_id: uuid.UUID | str) -> str:
    from app.modules.integrations.selectors import chosen_instagram_ids

    page = db.scalars(
        select(PageAccount).where(
            PageAccount.id == uuid.UUID(str(page_id)), PageAccount.provider == PROVIDER
        )
    ).first()
    if page is None or not page.instagram_user_id:
        return "gone"
    try:
        token = decrypt(page.token_encrypted)
    except DecryptionFailed:
        logger.exception("page %s could not be decrypted", page.id)
        return "unusable"
    read = 0
    for instagram_id in chosen_instagram_ids(db, page=page):
        try:
            media = list_recent_instagram_media(ig_user_id=instagram_id, token=token)
        except MetaError as exc:
            logger.info("recent instagram media failed for %s: %s", page.id, exc)
            return "failed"
        upsert_media(
            db,
            owner=page.owner,
            ad_account=None,
            page=page,
            kinds=IG_KINDS,
            assets=media,
            instagram_user_id=instagram_id,
        )
        db.commit()
        read += len(media)
    db.execute(
        update(PageAccount)
        .where(PageAccount.id == page.id)
        .values(instagram_media_synced_at=utcnow())
    )
    db.commit()
    return str(read)


# -- asking for a fresh read ----------------------------------------------------------


def request_media_refresh(db: Session, *, ad_account: AdAccount) -> None:
    from app.modules.ads.tasks import sync_media_task

    if not throttle.hit(
        bucket=REFRESH_BUCKET,
        key=f"{ad_account.provider}:{ad_account.external_id}",
        limit=REFRESH_LIMIT,
        window_seconds=MEDIA_REFRESH_SECONDS,
    ):
        raise MediaAskedRecently
    account_id = str(ad_account.id)
    on_commit(
        db, lambda: sync_media_task.apply_async((account_id,), queue=REFRESH_QUEUE)
    )


def refresh_media_on_open(db: Session, *, ad_account: AdAccount) -> bool:
    from app.modules.ads.tasks import sync_media_task

    fresh_after = utcnow() - timedelta(seconds=MEDIA_STALE_SECONDS)
    if ad_account.media_synced_at and ad_account.media_synced_at > fresh_after:
        return False
    if not throttle.hit(
        bucket=OPEN_BUCKET,
        key=f"{ad_account.provider}:{ad_account.external_id}",
        limit=REFRESH_LIMIT,
        window_seconds=MEDIA_STALE_SECONDS,
    ):
        return False
    account_id = str(ad_account.id)
    on_commit(
        db, lambda: sync_media_task.apply_async((account_id,), queue=REFRESH_QUEUE)
    )
    return True


def refresh_instagram_on_open(db: Session, *, page: PageAccount) -> bool:
    from app.modules.ads.tasks import sync_recent_instagram_task

    if not page.instagram_user_id:
        return False
    fresh_after = utcnow() - timedelta(seconds=MEDIA_RECENT_STALE_SECONDS)
    synced = page.instagram_media_synced_at
    if synced and synced > fresh_after:
        return False
    if not throttle.hit(
        bucket=RECENT_BUCKET,
        key=str(page.id),
        limit=REFRESH_LIMIT,
        window_seconds=MEDIA_RECENT_STALE_SECONDS,
    ):
        return False
    page_id = str(page.id)
    on_commit(db, lambda: sync_recent_instagram_task.delay(page_id))
    return True
