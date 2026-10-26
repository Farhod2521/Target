"""One variant, and one library square, as plain values for the API."""

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from app.modules.ads.constants import ALLOWED_VIDEO_TYPES, IG_KINDS, LibraryUpload
from app.modules.ads.models import LaunchCreative, MediaAsset
from app.modules.ads.selectors.library import LIBRARY_FILE_KINDS
from app.modules.ads.selectors.variants import is_uploading, words_touched

FILE_URL = "/api/v1/launch/{launch}/media/{position}/file"


def is_video(name: str) -> bool:
    """Whether an uploaded file is something to play rather than to show."""
    return (
        bool(name)
        and PurePosixPath(name).suffix.lstrip(".").lower() in ALLOWED_VIDEO_TYPES
    )


def asset_card(asset: MediaAsset | None) -> dict[str, Any] | None:
    if asset is None:
        return None
    return {
        "id": str(asset.id),
        "kind": asset.kind,
        "name": asset.name,
        "external_id": asset.external_id,
        "thumbnail_url": asset.thumbnail_url,
        "is_instagram": asset.is_instagram,
    }


def variant_card(variant: LaunchCreative, *, now: datetime) -> dict[str, Any]:
    """What one advert is made of."""
    upload = variant.media_upload or ""
    asset = variant.media_asset
    return {
        "id": str(variant.id),
        "position": variant.position,
        "asset": asset_card(asset),
        "upload_name": PurePosixPath(upload).name if upload else "",
        "file_url": FILE_URL.format(launch=variant.launch_id, position=variant.position)
        if upload
        else "",
        "is_upload": bool(upload),
        "is_video": is_video(upload),
        "primary_text": variant.primary_text,
        "headline": variant.headline,
        "description": variant.description,
        "is_post": bool(asset is not None and asset.kind in IG_KINDS),
        "words_touched": words_touched(variant=variant),
        "is_uploading": is_uploading(variant=variant, now=now),
        "upload_failed": variant.library_upload == LibraryUpload.FAILED,
        "brief": variant.brief,
    }


def library_tile(
    asset: MediaAsset,
    *,
    used_in: int,
    deleting: bool,
    delete_failed: bool,
    still_pending: bool = False,
) -> dict[str, Any]:
    """One square of the picker's grid, and what the owner may do to it."""
    is_file = asset.kind in LIBRARY_FILE_KINDS and bool(asset.ad_account_id)
    return {
        "asset": asset_card(asset),
        "used_in": used_in,
        "deleting": deleting,
        "delete_failed": delete_failed,
        "still_pending": still_pending,
        "is_file": is_file,
        "deletable": is_file and not used_in and not deleting,
    }


__all__ = ["asset_card", "is_video", "library_tile", "variant_card"]
