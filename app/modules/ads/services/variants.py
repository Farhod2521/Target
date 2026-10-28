"""Which pictures the ad is made out of, what the owner wrote about them, and the
two ways out of "too little per advert": more money, or fewer adverts."""

import logging
from typing import BinaryIO, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import storage
from app.common.db import utcnow
from app.modules.ads.constants import IG_KINDS, LAUNCH_RELATED_TYPE, TextMode
from app.modules.ads.exceptions import (
    AdTextMissing,
    LaunchMediaBlocked,
    MediaNotStored,
    ProposalLocked,
    TooManyCreatives,
    UnknownMedia,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.goals import goal_optimization
from app.modules.ads.selectors.library import AdSpread, ad_spread
from app.modules.ads.selectors.schedule import max_creatives
from app.modules.ads.selectors.variants import (
    launch_variants,
    variant_words,
    variants_needing_words,
)
from app.modules.audit.constants import EventName
from app.modules.businesses.models import Business

logger = logging.getLogger(__name__)
UPLOAD_FOLDER = "launch-media/%Y/%m/"
_BETWEEN = "\n\n"


class Upload(Protocol):
    filename: str | None
    file: BinaryIO


def add_media(
    db: Session,
    *,
    launch: CampaignLaunch,
    asset_ids: list[str],
    uploads: list[Upload],
) -> int:
    """Add pictures to this launch. Returns how many were added."""
    existing = launch_variants(db, launch=launch)
    limit = max_creatives()
    if len(existing) + len(asset_ids) + len(uploads) > limit:
        raise TooManyCreatives(limit=limit, chosen=len(existing))
    assets = _assets_for(db, launch=launch, asset_ids=asset_ids)
    position = len(existing)
    added = 0
    for asset in assets:
        _create(db, launch=launch, position=position, media_asset=asset)
        position += 1
        added += 1
    for upload in uploads:
        _create(db, launch=launch, position=position, upload=upload)
        position += 1
        added += 1
    db.flush()
    return added


def remove_variant(db: Session, *, launch: CampaignLaunch, position: int) -> None:
    """Drop one picture and the words that went with it."""
    if campaign_type_locked(launch=launch):
        raise ProposalLocked
    row = db.scalar(
        select(LaunchCreative).where(
            LaunchCreative.launch_id == launch.id, LaunchCreative.position == position
        )
    )
    if row is None:
        return
    name = row.media_upload
    db.delete(row)
    db.flush()
    for index, remaining in enumerate(launch_variants(db, launch=launch)):
        if remaining.position != index:
            remaining.position = index
            db.flush()
    if name:
        storage.delete(name)


def seed_words(db: Session, *, launch: CampaignLaunch) -> int:
    """Fill in the copy for variants that have none. Returns how many."""
    filled = 0
    for row in launch_variants(db, launch=launch):
        if row.primary_text or row.headline or row.description:
            continue
        words = variant_words(db, launch, row.position)
        if not any(words.values()):
            continue
        _write_words(row, words)
        filled += 1
    db.flush()
    return filled


def reseed_words(db: Session, *, launch: CampaignLaunch) -> int:
    """Replace every variant's copy with the newly proposed one."""
    filled = 0
    for row in variants_needing_words(db, launch=launch):
        _write_words(row, variant_words(db, launch, row.position))
        filled += 1
    db.flush()
    return filled


def forget_proposed_words(db: Session, *, launch: CampaignLaunch) -> int:
    """Clear the words a proposal wrote and nobody touched. Returns how many."""
    cleared = 0
    for row in variants_needing_words(db, launch=launch):
        proposed = variant_words(db, launch, row.position)
        if not any(proposed.values()):
            continue
        current = {
            "primary_text": row.primary_text,
            "headline": row.headline,
            "description": row.description,
        }
        if current != proposed:
            continue
        _write_words(row, {"primary_text": "", "headline": "", "description": ""})
        cleared += 1
    db.flush()
    return cleared


def _words(
    db: Session, launch: CampaignLaunch, position: int, asset: MediaAsset | None
) -> dict[str, str]:
    if asset is not None and asset.kind in IG_KINDS:
        return {"primary_text": asset.name, "headline": "", "description": ""}
    return variant_words(db, launch, position)


def _create(
    db: Session,
    *,
    launch: CampaignLaunch,
    position: int,
    media_asset: MediaAsset | None = None,
    upload: Upload | None = None,
) -> None:
    row = LaunchCreative(
        launch_id=launch.id,
        owner_id=launch.owner_id,
        position=position,
        media_asset_id=media_asset.id if media_asset is not None else None,
        group=max(0, len(launch.ad_groups or []) - 1),
        **_words(db, launch, position, media_asset),
    )
    if upload is not None:
        folder = storage.dated(UPLOAD_FOLDER, now=utcnow())
        filename = upload.filename or "upload"
        assembled = getattr(upload, "path", None)
        try:
            row.media_upload = (
                storage.move(assembled, folder=folder, filename=filename)
                if assembled is not None
                else storage.save(upload.file, folder=folder, filename=filename)
            )
        except OSError as exc:
            logger.exception("media.upload_failed", extra={"launch": str(launch.id)})
            raise MediaNotStored from exc
    db.add(row)
    db.flush()


def _assets_for(
    db: Session, *, launch: CampaignLaunch, asset_ids: list[str]
) -> list[MediaAsset]:
    import uuid

    if not asset_ids:
        return []
    try:
        wanted = [uuid.UUID(str(value)) for value in asset_ids]
    except ValueError as exc:
        raise UnknownMedia from exc
    found = {
        str(asset.id): asset
        for asset in db.scalars(
            select(MediaAsset).where(
                MediaAsset.owner_id == launch.owner_id,
                MediaAsset.provider == launch.provider,
                MediaAsset.id.in_(wanted),
            )
        )
    }
    if len(found) != len({str(value) for value in wanted}):
        raise UnknownMedia
    chosen = [
        found[str(asset_id)] for asset_id in dict.fromkeys(str(v) for v in wanted)
    ]
    if any(asset.is_blocked for asset in chosen):
        raise LaunchMediaBlocked
    return chosen


def _write_words(row: LaunchCreative, words: dict[str, str]) -> None:
    row.primary_text = words["primary_text"]
    row.headline = words["headline"]
    row.description = words["description"]


# -- the words the owner wrote ---------------------------------------------------------


def save_media_text(
    db: Session,
    *,
    launch: CampaignLaunch,
    mode: str,
    shared: str | None,
    briefs: dict[str, str],
) -> CampaignLaunch:
    """Write the text mode, the shared text and any per-advert texts."""
    from app.modules.ads.services.launch import same_wording, save_answers

    chosen = TextMode.EACH if mode == TextMode.EACH else TextMode.SHARED
    rows = variants_needing_words(db, launch=launch)
    for row in rows:
        text = briefs.get(str(row.id))
        if text is None or text == row.brief:
            continue
        row.brief = text
    db.flush()
    kept = _saved_shared(launch) if shared is None else shared.strip()
    if chosen == TextMode.EACH:
        offer = _BETWEEN.join(row.brief.strip() for row in rows if row.brief.strip())
    else:
        offer = kept
    if not same_wording(launch.answers.get("offer_text"), offer):
        forget_proposed_words(db, launch=launch)
    return save_answers(
        db, launch=launch, offer_text=offer, text_mode=str(chosen), shared_text=kept
    )


def _saved_shared(launch: CampaignLaunch) -> str:
    answers = launch.answers or {}
    return str(answers.get("shared_text", answers.get("offer_text", "")) or "")


def require_ad_texts(db: Session, *, launch: CampaignLaunch) -> None:
    """The owner's gate on "Davom etish". Raises ``AdTextMissing``."""
    rows = variants_needing_words(db, launch=launch)
    if not rows:
        return
    if launch.answers.get("text_mode") == TextMode.EACH:
        missing = sum(1 for row in rows if not row.brief.strip())
        if missing:
            raise AdTextMissing(missing=missing, each=True)
        return
    if not str(launch.answers.get("offer_text", "")).strip():
        raise AdTextMissing(missing=1, each=False)


# -- the spread ------------------------------------------------------------------------


def raise_budget_for_ads(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> int:
    """Lift the daily budget to what gives every advert its share."""
    from app.modules.ads.services.launch import save_answers
    from app.modules.ads.services.targeting import rebuild_targeting
    from app.modules.audit.services import emit

    if campaign_type_locked(launch=launch):
        raise ProposalLocked
    spread = _spread(db, launch)
    old = int(launch.daily_budget_minor or 0)
    if spread is None:
        return old
    wanted = spread.per_ad_minor * spread.chosen
    if wanted <= old:
        return old
    save_answers(db, launch=launch, daily_budget_minor=wanted)
    rebuild_targeting(db, launch=launch, business=business)
    emit(
        db,
        owner_id=launch.owner_id,
        name=EventName.LAUNCH_BUDGET_FITTED,
        aggregate_type=LAUNCH_RELATED_TYPE,
        aggregate_id=launch.id,
        payload={"previous": old, "daily_budget_minor": wanted},
    )
    return wanted


def keep_affordable_ads(db: Session, *, launch: CampaignLaunch) -> int:
    """Keep only as many adverts as today's budget carries - the first ones."""
    from app.modules.audit.services import emit

    if campaign_type_locked(launch=launch):
        raise ProposalLocked
    spread = _spread(db, launch)
    if spread is None:
        return 0
    keep = max(1, spread.carried)
    extra = [row.position for row in launch_variants(db, launch=launch)][keep:]
    for position in reversed(extra):
        remove_variant(db, launch=launch, position=position)
    emit(
        db,
        owner_id=launch.owner_id,
        name=EventName.LAUNCH_ADS_TRIMMED,
        aggregate_type=LAUNCH_RELATED_TYPE,
        aggregate_id=launch.id,
        payload={"kept": keep, "removed": len(extra)},
    )
    return len(extra)


def _spread(db: Session, launch: CampaignLaunch) -> AdSpread | None:
    return ad_spread(
        launch=launch,
        optimization_goal=goal_optimization(db, launch=launch),
        ads=len(launch_variants(db, launch=launch)),
    )
