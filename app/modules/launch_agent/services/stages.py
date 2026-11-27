"""The advert chat after its questions: pictures, the preparation, the
summary, and the one press that spends.

Where the conversation stands is read off the launch itself, never kept
beside it: the wizard's screens and this chat work the same row, and either
may have moved it. Every step is the wizard's own service - pictures are
added as its media step adds them, the preparation is the same worker, and
«Ishga tushirish» is the review screen's own create.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import DraftSection, LaunchStatus
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.variants import launch_variants
from app.modules.ads.services import creation, variants
from app.modules.ads.services import launch as launch_services
from app.modules.businesses.models import Business
from core.launch_agent import Ask, Option, Reply

logger = logging.getLogger(__name__)

ASKING: Final = "asking"
MEDIA: Final = "media"
PREPARING: Final = "preparing"
REVIEW: Final = "review"
CREATING: Final = "creating"
DONE: Final = "done"
FAILED: Final = "failed"
# The page asks again every few seconds while one of these stands.
WAITING: Final = frozenset({PREPARING, CREATING})

SLOT_MEDIA: Final = "media"
SLOT_PREPARE: Final = "prepare"
SLOT_LAUNCH: Final = "launch"
VALUE_DONE: Final = "done"
VALUE_RETRY: Final = "retry"
VALUE_START: Final = "start"
STAGE_SLOTS: Final = frozenset({SLOT_MEDIA, SLOT_PREPARE, SLOT_LAUNCH})

ASK_MEDIA: Final = "Reklama uchun post tanlang yoki rasm, video yuklang."
NO_MEDIA: Final = "Avval kamida bitta post tanlang yoki rasm, video yuklang."
SAY_PREPARING: Final = "Reklama tayyorlanmoqda: auditoriya va matnlar yozilyapti. Bir daqiqagacha vaqt oladi."
SAY_REVIEW: Final = "Reklama tayyor. Tekshirib, ishga tushiring."
SAY_CREATING: Final = "Reklama Meta'da yaratilmoqda…"
SAY_DONE: Final = (
    "Reklama yaratildi va yoqilmoqda. Holatini «Reklama» sahifasida ko'rasiz."
)
SAY_FAILED: Final = "Reklamani tayyorlab bo'lmadi."
SETTLED: Final = (
    "Sozlamalar saqlangan. O'zgartirish uchun «Sozlamalarni ko'rish» ni oching."
)
GENDERS: Final = {"male": "Erkaklar", "female": "Ayollar", "all": "Hamma"}
MAX_CARD_ADVERTS: Final = 3
MAX_CARD_INTERESTS: Final = 6


@dataclass(frozen=True, slots=True)
class Staged:
    """One answer past the questions: what is said, where it stands."""

    reply: Reply
    stage: str
    card: dict[str, Any] | None = None
    lines: tuple[str, ...] = field(default_factory=tuple)

    @property
    def wait(self) -> bool:
        return self.stage in WAITING


def stage_of(launch: CampaignLaunch, *, brief_ready: bool) -> str:
    """Where the launch stands, in the chat's words."""
    status = str(launch.status)
    if status == LaunchStatus.CREATED:
        return DONE
    if status in (LaunchStatus.FAILED, LaunchStatus.ROLLED_BACK):
        return FAILED
    if status == LaunchStatus.CREATING:
        return CREATING
    if status == LaunchStatus.BUILDING:
        return PREPARING
    if status == LaunchStatus.READY:
        return REVIEW
    return MEDIA if brief_ready else ASKING


def _open(label: str, slot: str, what: str) -> Option:
    return Option(label=label, slot=slot, value="", opens=what)


def _ask_media() -> Ask:
    return Ask(
        slot=SLOT_MEDIA,  # type: ignore[arg-type]
        text=ASK_MEDIA,
        options=(
            _open("Instagram postlaridan tanlash", SLOT_MEDIA, "media"),
            _open("Rasm yoki video yuklash", SLOT_MEDIA, "upload"),
        ),
        input="none",
    )


def _ask_launch() -> Ask:
    return Ask(
        slot=SLOT_LAUNCH,  # type: ignore[arg-type]
        text=SAY_REVIEW,
        options=(
            Option(
                label="Ishga tushirish",
                slot=SLOT_LAUNCH,
                value=VALUE_START,
                recommended=True,
            ),
            _open("Sozlamalarni ko'rish", SLOT_LAUNCH, "review"),
        ),
        input="none",
    )


def _ask_failed(launch: CampaignLaunch) -> Ask:
    written = draft_field.is_written(launch.draft)
    retry = Option(label="Qayta urinish", slot=SLOT_PREPARE, value=VALUE_RETRY)
    return Ask(
        slot=SLOT_PREPARE,  # type: ignore[arg-type]
        text=str(launch.error_message or SAY_FAILED),
        options=(
            (_open("Sozlamalarni ko'rish", SLOT_LAUNCH, "review"),)
            if written
            else (retry,)
        ),
        input="none",
    )


def card_of(db: Session, launch: CampaignLaunch) -> dict[str, Any]:
    """What was prepared, short enough to read in a chat. The review screen
    holds the whole of it."""
    draft = launch.draft or {}
    audience = draft_field.chosen(draft, DraftSection.AUDIENCE)
    audience = audience if isinstance(audience, dict) else {}
    interests = draft_field.chosen(draft, DraftSection.INTERESTS)
    labels = [
        str(item.get("label") or "")
        for item in (interests if isinstance(interests, list) else [])
        if isinstance(item, dict) and item.get("label")
    ]
    genders = [str(one) for one in audience.get("genders") or []]
    adverts = [
        {
            "primary_text": str(item.get("primary_text") or ""),
            "headline": str(item.get("headline") or ""),
        }
        for item in draft_field.creatives(draft)[:MAX_CARD_ADVERTS]
    ]
    return {
        "name": str(launch.campaign_name or ""),
        "media_count": len(launch_variants(db, launch=launch)),
        "age_min": audience.get("age_min"),
        "age_max": audience.get("age_max"),
        "genders": [GENDERS.get(one, one) for one in genders] or [GENDERS["all"]],
        "interests": labels[:MAX_CARD_INTERESTS],
        "interests_more": max(0, len(labels) - MAX_CARD_INTERESTS),
        "adverts": adverts,
    }


def staged(
    db: Session,
    *,
    launch: CampaignLaunch,
    base: Reply,
    lines: tuple[str, ...] = (),
) -> Staged:
    """The answer for a launch whose questions are all answered. ``base``
    is the engine's ready reply: its chips are kept, its words replaced by
    the stage's own."""
    stage = stage_of(launch, brief_ready=True)
    chips = base.chips
    if stage == MEDIA:
        return Staged(
            reply=Reply(lines=lines, ask=_ask_media(), chips=chips, ready=True),
            stage=stage,
        )
    if stage == PREPARING:
        return Staged(
            reply=Reply(lines=(*lines, SAY_PREPARING), chips=chips, ready=True),
            stage=stage,
        )
    if stage == REVIEW:
        return Staged(
            reply=Reply(lines=lines, ask=_ask_launch(), chips=chips, ready=True),
            stage=stage,
            card=card_of(db, launch),
        )
    if stage == CREATING:
        return Staged(
            reply=Reply(lines=(*lines, SAY_CREATING), chips=chips, ready=True),
            stage=stage,
        )
    if stage == DONE:
        return Staged(
            reply=Reply(lines=(*lines, SAY_DONE), chips=chips, ready=True),
            stage=stage,
        )
    return Staged(
        reply=Reply(lines=lines, ask=_ask_failed(launch), chips=chips, ready=True),
        stage=FAILED,
        card=card_of(db, launch) if draft_field.is_written(launch.draft) else None,
    )


def press(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    slot: str,
    value: str,
    asset_ids: list[str],
) -> tuple[str, ...]:
    """A press past the questions, carried out by the wizard's own service.
    Answers the lines to say when it was refused; empty when it went
    through. Commits what it starts, as those services do."""
    stage = stage_of(launch, brief_ready=True)
    try:
        if slot == SLOT_MEDIA and stage == MEDIA:
            if asset_ids:
                variants.add_media(db, launch=launch, asset_ids=asset_ids, uploads=[])
                db.flush()
            if not launch_variants(db, launch=launch):
                return (NO_MEDIA,)
            variants.require_ad_texts(db, launch=launch)
            launch_services.request_preparation(db, launch=launch)
            db.commit()
        elif slot == SLOT_PREPARE and stage == FAILED and value == VALUE_RETRY:
            launch_services.request_preparation(db, launch=launch)
            db.commit()
        elif slot == SLOT_LAUNCH and stage == REVIEW and value == VALUE_START:
            # The press that spends: the review screen's own create.
            creation.request_creation(db, launch=launch, business=business)
    except DomainError as refused:
        db.rollback()
        logger.info("launch_agent_press_refused", extra={"slot": slot})
        return (str(refused),)
    db.refresh(launch)
    return ()


__all__ = [
    "ASKING",
    "DONE",
    "FAILED",
    "MEDIA",
    "PREPARING",
    "REVIEW",
    "SETTLED",
    "STAGE_SLOTS",
    "Staged",
    "press",
    "stage_of",
    "staged",
]
