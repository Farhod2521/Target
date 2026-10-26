"""The pictures step: where pictures come from, what is chosen, what is busy."""

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ads.constants import (
    LIBRARY_POLL_TRIES,
    MAX_BRIEF_CHARS,
    MAX_IMAGE_MB,
    MAX_VIDEO_MB,
    MEDIA_POLL_TRIES,
    UPLOAD_CHUNK_BYTES,
    TextMode,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from app.modules.ads.selectors.cards import (
    FILE_URL,
    is_video,
    library_tile,
    variant_card,
)
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.library import (
    deleting_files,
    failed_deletes,
    media_usage,
    stills_pending,
)
from app.modules.ads.selectors.media import (
    ACCOUNT_SOURCE,
    MediaSource,
    instagram_source_page,
    media_library,
)
from app.modules.ads.selectors.schedule import max_creatives
from app.modules.ads.selectors.variants import launch_variants, uploads_in_flight

ACCEPT_TYPES = "image/jpeg,image/png,image/webp,video/mp4,video/quicktime"
VARIANT_BRIEF = "brief-v-"
ASSET_BRIEF = "brief-a-"


def chosen_source(sources: list[MediaSource], asked: str) -> str:
    """Which profile the grid shows: the one asked for, if it is offered."""
    if not sources:
        return ""
    allowed = {source.value for source in sources}
    return asked if asked in allowed else sources[0].value


def library_assets(
    db: Session, *, launch: CampaignLaunch, source: str
) -> list[MediaAsset]:
    return media_library(
        db,
        owner=launch.owner,
        provider=launch.provider,
        ad_account=launch.ad_account,
        page=launch_page(db, launch=launch),
        source=source,
    )


def media_status(
    db: Session, *, launch: CampaignLaunch, source: str, seen: int | None
) -> dict[str, Any]:
    """When the library was last read, and how much arrived since ``seen``."""
    account = launch.ad_account
    synced = account.media_synced_at if account else None
    shown = instagram_source_page(
        db, owner=launch.owner, page=launch_page(db, launch=launch), source=source
    )
    if shown is not None and shown.instagram_media_synced_at:
        synced = max(filter(None, (synced, shown.instagram_media_synced_at)))
    count = len(library_assets(db, launch=launch, source=source))
    return {
        "media_synced_at": synced,
        "media_seen": count if seen is None else seen,
        "media_arrived": 0 if seen is None else max(0, count - seen),
        "media_source": source,
    }


def busy_counts(
    db: Session, *, launch: CampaignLaunch, now: datetime
) -> dict[str, int]:
    """Files on their way up, on their way out, and covers being drawn."""
    uploading = uploads_in_flight(db, launch=launch, now=now)
    deleting = len(deleting_files(db, owner=launch.owner, now=now))
    stills = len(
        stills_pending(
            db, owner=launch.owner, ad_account_id=launch.ad_account_id, now=now
        )
    )
    return {
        "media_busy": uploading + deleting + stills,
        "media_uploading": uploading,
        "media_deleting": deleting,
        "media_stills": stills,
    }


def status_poll(
    db: Session,
    *,
    launch: CampaignLaunch,
    source: str,
    seen: int | None,
    since: int | None,
    busy_before: int,
    tries: int,
    now: datetime,
) -> dict[str, Any]:
    """The line beside the heading, and whether to keep asking."""
    status = media_status(db, launch=launch, source=source, seen=seen)
    synced = status["media_synced_at"]
    was = since if since is not None else (int(synced.timestamp()) if synced else 0)
    busy = busy_counts(db, launch=launch, now=now)
    moved = (synced is not None and synced.timestamp() > was + 1) or busy[
        "media_busy"
    ] < busy_before
    ceiling = LIBRARY_POLL_TRIES if busy["media_busy"] else MEDIA_POLL_TRIES
    return {
        **status,
        **busy,
        "media_since": was,
        "media_tries": tries,
        "media_updated": moved,
        "keep_polling": not moved and tries < ceiling,
    }


def text_panel(
    *, launch: CampaignLaunch, variants: list[LaunchCreative]
) -> dict[str, Any]:
    """What the text panel opens with: one text for all, or one each."""
    answers = launch.answers
    shared = answers.get("shared_text", answers.get("offer_text", ""))
    return {
        "mode": str(answers.get("text_mode") or TextMode.SHARED),
        "modes": TextMode.values,
        "shared": str(shared or ""),
        "max_chars": MAX_BRIEF_CHARS,
        "rows": [
            {
                "variant_id": str(variant.id),
                "name": _variant_name(variant),
                "thumb": _variant_thumb(variant),
                "post": bool(
                    variant.media_asset is not None and variant.media_asset.is_instagram
                ),
                "brief": variant.brief,
            }
            for variant in variants
        ],
    }


def _variant_name(variant: LaunchCreative) -> str:
    if variant.media_asset is not None:
        return variant.media_asset.name or variant.media_asset.kind
    return PurePosixPath(str(variant.media_upload or "")).name


def _variant_thumb(variant: LaunchCreative) -> str:
    if variant.media_asset is not None:
        return variant.media_asset.thumbnail_url
    if variant.media_upload and not is_video(variant.media_upload):
        return FILE_URL.format(launch=variant.launch_id, position=variant.position)
    return ""


def media_step(
    db: Session,
    *,
    launch: CampaignLaunch,
    sources: list[MediaSource],
    source: str,
    now: datetime,
) -> dict[str, Any]:
    """Everything the pictures step draws."""
    owner = launch.owner
    assets = library_assets(db, launch=launch, source=source)
    variants = launch_variants(db, launch=launch)
    cards = [variant_card(variant, now=now) for variant in variants]
    usage = media_usage(db, owner=owner, assets=assets)
    deleting = deleting_files(db, owner=owner, now=now)
    refused = failed_deletes(db, owner=owner, now=now)
    stills = stills_pending(
        db, owner=owner, ad_account_id=launch.ad_account_id, now=now
    )
    return {
        "sources": sources,
        "source": source,
        "is_library": source == ACCOUNT_SOURCE,
        "tiles": [
            library_tile(
                asset,
                used_in=usage.get(asset.id, 0),
                deleting=asset.external_id in deleting,
                delete_failed=asset.external_id in refused,
                still_pending=asset.id in stills,
            )
            for asset in assets
        ],
        "variants": cards,
        "chosen_asset_ids": [
            str(variant.media_asset_id)
            for variant in variants
            if variant.media_asset_id
        ],
        "uploading": [card for card in cards if card["is_uploading"]],
        "count": {"chosen": len(variants), "limit": max_creatives()},
        "text": text_panel(launch=launch, variants=variants),
        "max_image_mb": MAX_IMAGE_MB,
        "max_video_mb": MAX_VIDEO_MB,
        "accept_types": ACCEPT_TYPES,
        "upload_chunk_bytes": UPLOAD_CHUNK_BYTES,
        **busy_counts(db, launch=launch, now=now),
        **media_status(db, launch=launch, source=source, seen=None),
    }


__all__ = [
    "ACCEPT_TYPES",
    "ASSET_BRIEF",
    "VARIANT_BRIEF",
    "busy_counts",
    "chosen_source",
    "library_assets",
    "media_status",
    "media_step",
    "status_poll",
    "text_panel",
]
