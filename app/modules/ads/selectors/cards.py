"""One variant, and one library square, as plain values for the API."""

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Final

from app.modules.ads.constants import ALLOWED_VIDEO_TYPES, IG_KINDS, LibraryUpload
from app.modules.ads.models import LaunchCreative, MediaAsset
from app.modules.ads.selectors.launch_settings import post_address
from app.modules.ads.selectors.library import LIBRARY_FILE_KINDS
from app.modules.ads.selectors.variants import is_uploading, words_touched

FILE_URL = "/api/v1/launch/{launch}/media/{position}/file"

# Why Meta will not advertise a post, read from its own English sentence.
# Measured on the production copy 2026-11-09: these three are every reason
# Meta gave (118 tappable, 55 audio, 41 too long); anything else is "other".
BLOCKED_REASONS: Final = (
    ("music", "audio"),
    ("tappable", "tappable"),
    ("too_long", "15 minutes"),
)


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
        # Only a post has a page to open; a file's address is the file itself.
        "permalink_url": post_address(asset),
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
        "upload_refusal": variant.upload_refusal or None,
        "brief": variant.brief,
    }


def blocked_reason(asset: MediaAsset) -> str:
    """Which of the known refusals this is; empty for a post Meta allows."""
    if asset.is_eligible is not False:
        return ""
    said = asset.ineligible_reason.lower()
    return next((kind for kind, word in BLOCKED_REASONS if word in said), "other")


def grid_facts(asset: MediaAsset) -> dict[str, Any]:
    """What a grid square says about the file beyond its picture."""
    posted = asset.created_at_provider
    return {
        "is_eligible": asset.is_eligible,
        "blocked_reason": blocked_reason(asset),
        "width": asset.width,
        "height": asset.height,
        "created_at": posted.isoformat() if posted else None,
        "duration": asset.duration_seconds,
        "is_carousel": asset.is_carousel,
        "is_reel": asset.product == "REELS",
    }


def library_tile(
    asset: MediaAsset,
    *,
    used_in: int,
    deleting: bool,
    delete_failed: bool,
    still_pending: bool = False,
    delete_refusal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One square of the picker's grid, and what the owner may do to it."""
    is_file = asset.kind in LIBRARY_FILE_KINDS and bool(asset.ad_account_id)
    card = asset_card(asset)
    return {
        "asset": {**card, **grid_facts(asset)} if card else card,
        "used_in": used_in,
        "deleting": deleting,
        "delete_failed": delete_failed,
        "delete_refusal": delete_refusal,
        "still_pending": still_pending,
        "is_file": is_file,
        "deletable": is_file and not used_in and not deleting,
    }


__all__ = [
    "BLOCKED_REASONS",
    "asset_card",
    "blocked_reason",
    "grid_facts",
    "is_video",
    "library_tile",
    "variant_card",
]
