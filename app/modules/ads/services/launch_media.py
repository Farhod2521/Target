"""Getting the owner's pictures to the provider, before anything is created."""

import logging
import time
from dataclasses import dataclass

from adskit.errors import MediaTooLarge
from adskit.refs import ExternalRef
from metaads.assets import InstagramSlide, MetaAssets
from metaads.specs import CAROUSEL_MAX_CARDS, CAROUSEL_MIN_CARDS
from sqlalchemy.orm import Session

from app.common import storage
from app.common.db import utcnow
from app.modules.ads.constants import (
    ALLOWED_VIDEO_TYPES,
    IG_KINDS,
    VIDEO_POLL_ATTEMPTS,
    VIDEO_POLL_SECONDS,
    MediaKind,
)
from app.modules.ads.exceptions import (
    LaunchMediaBlocked,
    LaunchMediaForeign,
    LaunchMediaMissing,
    LaunchMediaOffPage,
    LaunchMediaTooLarge,
    LaunchMediaUnsupported,
    MediaStillUploading,
    VideoNotReady,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from app.modules.ads.selectors.media import post_account
from app.modules.ads.selectors.variants import (
    is_uploading,
    launch_variants,
    promotes_post,
)
from app.modules.ads.services.access import profile_token
from app.modules.integrations.models import PageAccount
from core.targeting import BuiltTargeting

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UploadedMedia:
    """One picture as the provider now names it."""

    image_hash: str = ""
    video_id: str = ""
    thumbnail_url: str = ""
    library_still: str = ""
    cards: tuple["UploadedMedia", ...] = ()


def check_media(
    db: Session, launch: CampaignLaunch, *, page: PageAccount, built: BuiltTargeting
) -> None:
    """The media rule, answered without touching the provider."""
    variants = launch_variants(db, launch=launch)
    if not variants:
        raise LaunchMediaMissing
    for variant in variants:
        _check_one(db, variant, page=page, built=built)


def upload_all(
    db: Session,
    *,
    launch: CampaignLaunch,
    account: ExternalRef,
    token: str,
    dry_run: bool,
    page: PageAccount,
    built: BuiltTargeting,
) -> list[UploadedMedia]:
    """Send every variant's picture, in order, and wait for the videos."""
    check_media(db, launch, page=page, built=built)
    if not dry_run:
        refuse_foreign_pictures(db, launch=launch, account=account, token=token)
    assets = MetaAssets()
    uploaded = [
        UploadedMedia()
        if promotes_post(variant=variant, built=built)
        else _send(
            variant=variant,
            assets=assets,
            account=account,
            token=token,
            dry_run=dry_run,
        )
        for variant in launch_variants(db, launch=launch)
    ]
    if dry_run:
        return [
            _with_still(item=item, still=item.library_still)
            if item.library_still
            else item
            for item in uploaded
        ]
    pending = [
        piece.video_id
        for item in uploaded
        for piece in item.cards or (item,)
        if piece.video_id and not piece.thumbnail_url
    ]
    if pending:
        _wait_for_all(assets=assets, video_ids=pending, token=token)
    return [_with_thumbnail(item=item, assets=assets, token=token) for item in uploaded]


def refuse_foreign_pictures(
    db: Session, *, launch: CampaignLaunch, account: ExternalRef, token: str
) -> None:
    """Refuse a launch whose library picture this ad account does not own."""
    from app.modules.ads.services.swap import foreign_pictures

    library = [
        asset
        for variant in launch_variants(db, launch=launch)
        if (asset := variant.media_asset) is not None and asset.kind == MediaKind.IMAGE
    ]
    foreign = foreign_pictures(
        provider=account.provider,
        account_id=account.id,
        hashes=[asset.external_id for asset in library],
        token=token,
    )
    for asset in library:
        if asset.external_id in foreign:
            raise LaunchMediaForeign(file_name=asset.name or asset.external_id)


def _check_one(
    db: Session, variant: LaunchCreative, *, page: PageAccount, built: BuiltTargeting
) -> None:
    from app.modules.integrations.selectors.pages import chosen_instagram_ids

    if is_uploading(variant=variant, now=utcnow()):
        raise MediaStillUploading
    if variant.media_asset_id:
        asset = variant.media_asset
        if asset is None or asset.kind == MediaKind.POST:
            raise LaunchMediaUnsupported
        if asset.is_eligible is False:
            raise LaunchMediaBlocked
        if promotes_post(variant=variant, built=built) and (
            asset.page_id != page.id
            or post_account(asset=asset, page=page)
            not in chosen_instagram_ids(db, page=page)
        ):
            raise LaunchMediaOffPage
        return
    if not variant.media_upload:
        raise LaunchMediaMissing


def _send(
    *,
    variant: LaunchCreative,
    assets: MetaAssets,
    account: ExternalRef,
    token: str,
    dry_run: bool,
) -> UploadedMedia:
    if variant.media_asset_id:
        return _from_library(
            variant=variant,
            assets=assets,
            account=account,
            token=token,
            dry_run=dry_run,
        )
    name = variant.media_upload.rsplit("/", 1)[-1]
    try:
        with storage.media_path(variant.media_upload).open("rb") as handle:
            if not _is_video(name):
                image = assets.upload_image(
                    account=account,
                    data=handle.read(),
                    filename=name,
                    token=token,
                    dry_run=dry_run,
                )
                return UploadedMedia(image_hash=image)
            video = assets.upload_video(
                account=account,
                file=handle,
                file_size=storage.size(variant.media_upload),
                filename=name,
                token=token,
                dry_run=dry_run,
            )
    except MediaTooLarge as exc:
        raise LaunchMediaTooLarge(file_name=name) from exc
    except FileNotFoundError as exc:
        raise LaunchMediaMissing from exc
    return UploadedMedia(video_id=video)


def _from_library(
    *,
    variant: LaunchCreative,
    assets: MetaAssets,
    account: ExternalRef,
    token: str,
    dry_run: bool,
) -> UploadedMedia:
    asset = variant.media_asset
    if asset is None:
        raise LaunchMediaUnsupported
    if asset.kind in IG_KINDS:
        return _from_instagram(
            asset=asset, assets=assets, account=account, token=token, dry_run=dry_run
        )
    if asset.kind == MediaKind.VIDEO:
        return UploadedMedia(
            video_id=asset.external_id, library_still=asset.thumbnail_url
        )
    return UploadedMedia(image_hash=asset.external_id)


def _from_instagram(
    *,
    asset: MediaAsset,
    assets: MetaAssets,
    account: ExternalRef,
    token: str,
    dry_run: bool,
) -> UploadedMedia:
    """A post on Instagram, copied onto the ad account so an ad can use it."""
    token_of_page = profile_token(asset)
    if asset.kind == MediaKind.IG_IMAGE:
        slides = assets.instagram_slides(
            media_id=asset.external_id, token=token_of_page
        )
        if slides:
            return _carousel(
                asset=asset,
                slides=slides,
                assets=assets,
                account=account,
                token=token,
                dry_run=dry_run,
            )
    source = assets.instagram_source(media_id=asset.external_id, token=token_of_page)
    if not source:
        logger.info(
            "instagram source withheld",
            extra={"asset": asset.external_id, "kind": asset.kind},
        )
        raise LaunchMediaBlocked
    if asset.kind == MediaKind.IG_VIDEO:
        video = assets.import_video(
            account=account, media_url=source, token=token, dry_run=dry_run
        )
        return UploadedMedia(video_id=video)
    image = assets.import_image(
        account=account, media_url=source, token=token, dry_run=dry_run
    )
    return UploadedMedia(image_hash=image)


def _carousel(
    *,
    asset: MediaAsset,
    slides: list[InstagramSlide],
    assets: MetaAssets,
    account: ExternalRef,
    token: str,
    dry_run: bool,
) -> UploadedMedia:
    if len(slides) < CAROUSEL_MIN_CARDS:
        raise LaunchMediaBlocked
    if len(slides) > CAROUSEL_MAX_CARDS:
        logger.info(
            "instagram carousel trimmed",
            extra={"asset": asset.external_id, "slides": len(slides)},
        )
    kept = slides[:CAROUSEL_MAX_CARDS]
    if any(not slide.media_url for slide in kept):
        raise LaunchMediaBlocked
    return UploadedMedia(
        cards=tuple(
            _slide(
                slide=slide,
                assets=assets,
                account=account,
                token=token,
                dry_run=dry_run,
            )
            for slide in kept
        )
    )


def _slide(
    *,
    slide: InstagramSlide,
    assets: MetaAssets,
    account: ExternalRef,
    token: str,
    dry_run: bool,
) -> UploadedMedia:
    if slide.is_video:
        return UploadedMedia(
            video_id=assets.import_video(
                account=account, media_url=slide.media_url, token=token, dry_run=dry_run
            )
        )
    return UploadedMedia(
        image_hash=assets.import_image(
            account=account, media_url=slide.media_url, token=token, dry_run=dry_run
        )
    )


def _with_thumbnail(
    *, item: UploadedMedia, assets: MetaAssets, token: str
) -> UploadedMedia:
    if item.cards:
        return UploadedMedia(
            cards=tuple(
                _with_thumbnail(item=card, assets=assets, token=token)
                for card in item.cards
            )
        )
    if not item.video_id or item.thumbnail_url:
        return item
    frame = assets.video_thumbnail(video_id=item.video_id, token=token)
    return _with_still(item=item, still=frame or item.library_still)


def _with_still(*, item: UploadedMedia, still: str) -> UploadedMedia:
    return UploadedMedia(
        video_id=item.video_id, thumbnail_url=still, library_still=item.library_still
    )


def _wait_for_all(*, assets: MetaAssets, video_ids: list[str], token: str) -> None:
    waiting = list(video_ids)
    for _attempt in range(VIDEO_POLL_ATTEMPTS):
        waiting = [
            video_id
            for video_id in waiting
            if not assets.video_ready(video_id=video_id, token=token)
        ]
        if not waiting:
            return
        time.sleep(VIDEO_POLL_SECONDS)
    raise VideoNotReady


def _is_video(filename: str) -> bool:
    return filename.rsplit(".", 1)[-1].lower() in ALLOWED_VIDEO_TYPES
