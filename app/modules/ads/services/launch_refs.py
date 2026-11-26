"""Keeping a launch's provider ids in step with what the provider still has."""

import logging
from collections.abc import Iterable

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import Session

from app.modules.ads import refs as ref_field
from app.modules.ads.constants import LaunchStep
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.campaign_type import BUILT_STATUSES

logger = logging.getLogger(__name__)
GONE_STEPS = (LaunchStep.CAMPAIGN, LaunchStep.ADSET, LaunchStep.AD)


def release_launch_refs(db: Session, *, step: str, external_ids: Iterable[str]) -> int:
    """Take ids the provider no longer has off the launches not yet made.

    A launch being created or created keeps its ids: they are the record of
    what it made. One still in preparation - failed, rolled back, or ready
    again - holds them only as objects to reuse or clean up, and an id that
    is gone would lock it for good. Returns how many ids were taken off.
    """
    gone = {str(item) for item in external_ids if item}
    if not gone:
        return 0
    text = cast(CampaignLaunch.created_refs, Text)
    rows = db.scalars(
        select(CampaignLaunch).where(
            CampaignLaunch.status.not_in([str(status) for status in BUILT_STATUSES]),
            or_(*(text.like(f'%"{name}"%') for name in GONE_STEPS)),
        )
    ).all()
    released = 0
    for launch in rows:
        held = [
            item
            for item in ref_field.ref_ids(launch.created_refs or {}, step)
            if item in gone
        ]
        if not held:
            continue
        refs = fresh(launch, "created_refs")
        for external_id in held:
            ref_field.clear(refs, step, external_id)
        released += len(held)
        logger.info(
            "launch %s let go of %s %s the provider no longer has",
            launch.id,
            step,
            held,
        )
    return released
