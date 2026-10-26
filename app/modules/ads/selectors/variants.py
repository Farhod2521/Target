"""What one launch is about to build."""

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    IG_KINDS,
    LIBRARY_WORK_FRESH_MINUTES,
    LibraryUpload,
    PostRoute,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative


class Destination(Protocol):
    @property
    def needs_phone(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class MediaCount:
    """How many pictures a launch has, and how many more it may take."""

    chosen: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.chosen)

    @property
    def is_full(self) -> bool:
        return self.chosen >= self.limit


def launch_variants(db: Session, *, launch: CampaignLaunch) -> list[LaunchCreative]:
    """Every ad this launch will build, in the order they are numbered."""
    return list(
        db.scalars(
            select(LaunchCreative)
            .where(LaunchCreative.launch_id == launch.id)
            .options(selectinload(LaunchCreative.media_asset))
            .order_by(LaunchCreative.position)
        )
    )


def promotes_post(*, variant: LaunchCreative, built: Destination) -> bool:
    return post_route(variant=variant, built=built) == PostRoute.PROMOTED


def post_route(*, variant: LaunchCreative, built: Destination) -> PostRoute | None:
    """How an Instagram post becomes an advert, and why - or ``None``."""
    if not _is_post(variant):
        return None
    if built.needs_phone:
        return PostRoute.COPIED_FOR_CALLS
    if words_touched(variant=variant):
        return PostRoute.COPIED_FOR_WORDS
    return PostRoute.PROMOTED


def same_words(first: str, second: str) -> bool:
    return _plain(first) == _plain(second)


def _plain(text: str) -> str:
    joined = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    lines = joined.replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def words_touched(*, variant: LaunchCreative) -> bool:
    """Whether the owner has written anything of their own for this advert."""
    if variant.headline.strip() or variant.description.strip():
        return True
    asset = variant.media_asset
    caption = asset.name if asset else ""
    return not same_words(variant.primary_text, caption)


def variants_needing_words(
    db: Session, *, launch: CampaignLaunch
) -> list[LaunchCreative]:
    return [row for row in launch_variants(db, launch=launch) if not _is_post(row)]


def is_post(variant: LaunchCreative) -> bool:
    return _is_post(variant)


def _is_post(variant: LaunchCreative) -> bool:
    asset = variant.media_asset
    return asset is not None and asset.kind in IG_KINDS


def post_caption_of(variant: LaunchCreative) -> str | None:
    if not _is_post(variant):
        return None
    asset = variant.media_asset
    return str(asset.name or "") if asset is not None else None


def is_uploading(*, variant: LaunchCreative, now: datetime) -> bool:
    if variant.library_upload != LibraryUpload.PENDING:
        return False
    return variant.updated_at >= now - timedelta(minutes=LIBRARY_WORK_FRESH_MINUTES)


def uploads_in_flight(db: Session, *, launch: CampaignLaunch, now: datetime) -> int:
    since = now - timedelta(minutes=LIBRARY_WORK_FRESH_MINUTES)
    return int(
        db.scalar(
            select(func.count(LaunchCreative.id)).where(
                LaunchCreative.launch_id == launch.id,
                LaunchCreative.library_upload == LibraryUpload.PENDING,
                LaunchCreative.updated_at >= since,
            )
        )
        or 0
    )


def post_caption(db: Session, *, launch: CampaignLaunch) -> str:
    for variant in launch_variants(db, launch=launch):
        asset = variant.media_asset
        if asset is not None and asset.kind in IG_KINDS:
            return str(asset.name or "").strip()
    return ""


def variant_upload(db: Session, *, launch: CampaignLaunch, position: int) -> str | None:
    """One variant's stored file name, or ``None`` - for the route that serves it."""
    found = db.scalar(
        select(LaunchCreative.media_upload).where(
            LaunchCreative.launch_id == launch.id, LaunchCreative.position == position
        )
    )
    return found or None


def variant_words(db: Session, launch: CampaignLaunch, position: int) -> dict[str, str]:
    """The copy proposed for one variant, from what Claude wrote."""
    empty = {"primary_text": "", "headline": "", "description": ""}
    items = _as_list(draft_field.proposal(launch.draft or {}, "creative"))
    if not items:
        return empty
    rows = launch_variants(db, launch=launch)
    here = next((row for row in rows if row.position == position), None)
    if here is not None and _is_post(here):
        return empty
    index = sum(1 for row in rows if row.position < position and not _is_post(row))
    item = items[index] if index < len(items) else items[-1]
    return {
        "primary_text": str(item.get("primary_text", "")),
        "headline": str(item.get("headline", "")),
        "description": str(item.get("description", "")),
    }


def _as_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []
