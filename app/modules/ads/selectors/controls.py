from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, object_session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    SWITCHED_OFF,
    Delivery,
    ManagedLevel,
)
from app.modules.ads.models import Ad
from app.modules.ads.selectors.actions import account_of, budget_floor
from app.modules.ads.selectors.delivery import (
    ancestors_of,
    blocked_above,
    parent_switched_off,
)
from app.modules.ads.selectors.early_touch import hours_to_wait
from core.agent import ObjectState, check_status_change
from core.agent.guardrails import ACTIVE, PAUSED, resets_learning


@dataclass(frozen=True, slots=True)
class Controls:
    level: str
    external_id: str
    can_pause: bool
    can_resume: bool
    can_budget: bool
    warns_learning: bool
    blocked_above: bool
    daily_budget_minor: int | None
    currency: str
    provider: str
    floor_minor: int
    parent_off: bool = False
    watched_account: bool = False
    early_hours: int = 0


def controls_for(*, target: Any, level: str) -> Controls:
    state = ObjectState(
        delivery=str(getattr(target, "delivery", "unknown")),
        is_learning=bool(getattr(target, "is_learning", False)),
        daily_budget_minor=getattr(target, "daily_budget_minor", None),
    )
    switched_off = state.delivery in SWITCHED_OFF
    faulted = state.delivery == Delivery.REJECTED and bool(
        getattr(target, "issue_codes", None)
    )
    watched = not account_of(target=target, level=level).is_active
    return Controls(
        level=level,
        external_id=str(target.external_id),
        can_pause=check_status_change(state=state, wanted=PAUSED).allowed
        and (not switched_off)
        and (not faulted)
        and (not watched),
        can_resume=check_status_change(state=state, wanted=ACTIVE).allowed
        and switched_off
        and (not watched),
        can_budget=state.daily_budget_minor is not None
        and (not state.is_learning)
        and (not watched),
        warns_learning=resets_learning(state=state),
        blocked_above=blocked_above(target=target, level=level),
        daily_budget_minor=state.daily_budget_minor,
        currency=str(getattr(target, "currency", "")),
        provider=str(getattr(target, "provider", "")),
        floor_minor=budget_floor(target=target, level=level),
        parent_off=parent_switched_off(target=target, level=level),
        watched_account=watched,
        early_hours=_early_hours(target=target, level=level),
    )


def _early_hours(*, target: Any, level: str) -> int:
    known = getattr(target, "early_hours", None)
    if known is not None:
        return int(known)
    db = object_session(target)
    if db is None:
        return 0
    return hours_to_wait(
        db,
        owner=target.owner,
        level=level,
        external_id=str(target.external_id),
        now=utcnow(),
    )


def clusters_beside(
    db: Session, *, owner: User, target: Any, level: str
) -> list[tuple[str, Any]]:
    from app.modules.ads.models import AdSet, Campaign

    if level != ManagedLevel.CAMPAIGN:
        return ancestors_of(target=target, level=level)
    ads = db.scalars(
        select(Ad)
        .join(AdSet, AdSet.id == Ad.adset_id)
        .options(
            joinedload(Ad.adset)
            .joinedload(AdSet.campaign)
            .joinedload(Campaign.ad_account)
        )
        .where(Ad.owner_id == owner.id, AdSet.campaign_id == target.id)
        .order_by(Ad.name)
    )
    return [(ManagedLevel.AD, ad) for ad in ads]


__all__ = ["Controls", "clusters_beside", "controls_for"]
