from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Final

from metaads.writing import is_dry_run_id
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import SWITCHED_OFF, Delivery, LaunchStep, ManagedLevel
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch

EARLY_TOUCH_HOURS: Final = 72
_MADE: Final = (LaunchStep.CAMPAIGN, LaunchStep.ADSET, LaunchStep.AD)
_NOT_RUNNING: Final = frozenset({*SWITCHED_OFF, Delivery.FINISHED})


@dataclass(frozen=True, slots=True)
class YoungLaunches:
    now: datetime
    born: Mapping[str, datetime]

    def hours_left(self, *external_ids: str) -> int:
        times = [self.born[i] for i in external_ids if i in self.born]
        if not times:
            return 0
        left = max(times) + timedelta(hours=EARLY_TOUCH_HOURS) - self.now
        return max(ceil(left.total_seconds() / 3600), 0)


def young_launches(db: Session, *, owner: User, now: datetime) -> YoungLaunches:
    from app.modules.ads.models import GoalCampaign

    cut = now - timedelta(hours=EARLY_TOUCH_HOURS)
    rows = db.execute(
        select(
            CampaignLaunch.created_refs,
            CampaignLaunch.finished_at,
            CampaignLaunch.started_at,
            GoalCampaign.external_id,
        )
        .outerjoin(GoalCampaign, GoalCampaign.id == CampaignLaunch.goal_campaign_id)
        .where(
            CampaignLaunch.owner_id == owner.id,
            or_(
                CampaignLaunch.finished_at >= cut,
                and_(
                    CampaignLaunch.finished_at.is_(None),
                    CampaignLaunch.started_at >= cut,
                ),
            ),
        )
    )
    born: dict[str, datetime] = {}
    for created_refs, finished_at, started_at, shared_id in rows:
        made_at = finished_at or started_at
        if made_at is None:
            continue
        ids = [i for step in _MADE for i in ref_field.ref_ids(created_refs or {}, step)]
        for external_id in (*ids, shared_id or ""):
            if not external_id or is_dry_run_id(external_id):
                continue
            if external_id not in born or born[external_id] < made_at:
                born[external_id] = made_at
    return YoungLaunches(now=now, born=born)


def hours_to_wait(
    db: Session, *, owner: User, level: str, external_id: str, now: datetime
) -> int:
    lineage = _running_lineage(db, owner=owner, level=level, external_id=external_id)
    if not lineage:
        return 0
    return young_launches(db, owner=owner, now=now).hours_left(*lineage)


def early_hours_on(*, target: Any, level: str, young: YoungLaunches) -> int:
    if str(getattr(target, "delivery", "")) in _NOT_RUNNING:
        return 0
    ids = [str(target.external_id)]
    if level == ManagedLevel.AD:
        ids.append(str(target.adset.external_id))
    return young.hours_left(*ids)


def _running_lineage(
    db: Session, *, owner: User, level: str, external_id: str
) -> tuple[str, ...]:
    if level == ManagedLevel.AD:
        ad = db.execute(
            select(Ad.delivery, AdSet.external_id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(Ad.owner_id == owner.id, Ad.external_id == external_id)
            .limit(1)
        ).first()
        if ad is None or ad[0] in _NOT_RUNNING:
            return ()
        return (external_id, ad[1])
    model = AdSet if level == ManagedLevel.ADSET else Campaign
    delivery = db.scalar(
        select(model.delivery)
        .where(model.owner_id == owner.id, model.external_id == external_id)
        .limit(1)
    )
    if delivery is None or delivery in _NOT_RUNNING:
        return ()
    return (external_id,)


__all__ = [
    "EARLY_TOUCH_HOURS",
    "YoungLaunches",
    "early_hours_on",
    "hours_to_wait",
    "young_launches",
]
