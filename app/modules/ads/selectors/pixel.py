"""Which tag on the owner's own site this launch reports through."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.modules.ads.constants import PIXEL_ID
from app.modules.ads.models import CampaignLaunch
from app.modules.integrations.models import PixelAccount
from core.targeting import ConversionSource


def _usable(launch: CampaignLaunch) -> Select[tuple[PixelAccount]]:
    return select(PixelAccount).where(
        PixelAccount.owner_id == launch.owner_id,
        PixelAccount.provider == launch.provider,
        PixelAccount.ad_account_id == launch.ad_account_id,
        PixelAccount.is_unavailable.is_(False),
    )


def usable_pixels(db: Session, *, launch: CampaignLaunch) -> tuple[PixelAccount, ...]:
    return tuple(
        db.scalars(
            _usable(launch).order_by(PixelAccount.is_active.desc(), PixelAccount.name)
        )
    )


def chosen_pixel(db: Session, *, launch: CampaignLaunch) -> PixelAccount | None:
    """The tag this launch will name, or ``None`` when there is none to name."""
    named = str(launch.answers.get(PIXEL_ID) or "")
    if named:
        found = db.scalar(_usable(launch).where(PixelAccount.external_id == named))
        if found is not None:
            return found
    return db.scalar(_usable(launch).where(PixelAccount.is_active.is_(True)).limit(1))


def launch_conversion_source(
    db: Session, *, launch: CampaignLaunch
) -> ConversionSource | None:
    pixel = chosen_pixel(db, launch=launch)
    if pixel is None:
        return None
    return ConversionSource(external_id=pixel.external_id, name=pixel.name)


@dataclass(frozen=True, slots=True)
class PixelOption:
    external_id: str
    name: str
    is_chosen: bool
    last_fired_at: datetime | None
    events_seen: int


def pixel_choices(db: Session, *, launch: CampaignLaunch) -> tuple[PixelOption, ...]:
    """The tab's pixel list, or nothing when there is nothing to choose."""
    found = usable_pixels(db, launch=launch)
    if len(found) < 2:
        return ()
    chosen = chosen_pixel(db, launch=launch)
    chosen_id = chosen.external_id if chosen is not None else ""
    return tuple(
        PixelOption(
            external_id=row.external_id,
            name=row.name or row.external_id,
            is_chosen=row.external_id == chosen_id,
            last_fired_at=row.last_fired_at,
            events_seen=len(row.recent_events)
            if isinstance(row.recent_events, list)
            else 0,
        )
        for row in found
    )
