"""What one running campaign's edit dialog may change, on which object; and what one advert shows."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    PREVIEW_AD_FORMAT,
    PREVIEW_FRESH_MINUTES,
    ManagedLevel,
)
from app.modules.ads.models import AdCreative, AdPreview, AdSet, Campaign
from app.modules.ads.selectors.controls import Controls, controls_for
from core.agent import ObjectState, check_limit_change, check_targeting_change
from core.targeting import AudienceSketch, describe
from core.targeting.validators import MIN_RADIUS_KM, SPECIAL_MIN_RADIUS_KM

_NO_CATEGORY: Final = "NONE"


@dataclass(frozen=True, slots=True)
class BudgetTarget:
    """The object the daily figure is written to, and what it says now."""

    level: str
    external_id: str
    controls: Controls


@dataclass(frozen=True, slots=True)
class AudienceTarget:
    """The ad set whose audience the dialog would replace, and its state."""

    external_id: str
    spec: dict[str, Any]
    sketch: AudienceSketch
    can_change: bool
    is_learning: bool
    allows_gender: bool
    min_radius_km: int


@dataclass(frozen=True, slots=True)
class LimitsTarget:
    """When the campaign stops, and how much it may spend before it does."""

    campaign_external_id: str
    adset_external_id: str
    end_time: datetime | None
    spend_cap_minor: int | None
    currency: str
    can_change: bool
    offers_spend_cap: bool = True

    @property
    def offers_end_time(self) -> bool:
        return bool(self.adset_external_id)


@dataclass(frozen=True, slots=True)
class Editable:
    """One campaign, and the objects its dialog would write to."""

    campaign: Campaign
    groups: int
    budget: BudgetTarget | None
    audience: AudienceTarget | None
    limits: LimitsTarget | None
    group: AdSet | None = None

    @property
    def is_split(self) -> bool:
        return self.groups > 1


def editable(db: Session, *, campaign: Campaign, group: str = "") -> Editable | None:
    """Which of this campaign's settings the dialog can reach, from the mirror."""
    from app.modules.ads.selectors.launched import goal_campaign_ids

    groups = list(campaign.adsets)
    chosen = None
    if group:
        chosen = next((row for row in groups if row.external_id == group), None)
        if chosen is None:
            return None
        groups = [chosen]
    ours = campaign.external_id in goal_campaign_ids(db, owner=campaign.owner_id)
    limits = _limits(campaign=campaign, groups=groups)
    if limits is not None and ours:
        limits = replace(limits, offers_spend_cap=False)
    return Editable(
        campaign=campaign,
        groups=len(groups),
        budget=_budget(campaign=campaign, groups=groups),
        audience=_audience(campaign=campaign, groups=groups),
        limits=limits,
        group=chosen,
    )


def _limits(*, campaign: Campaign, groups: list[AdSet]) -> LimitsTarget | None:
    if not groups:
        return None
    state = ObjectState(
        delivery=str(campaign.delivery),
        is_learning=False,
        daily_budget_minor=campaign.daily_budget_minor,
    )
    return LimitsTarget(
        campaign_external_id=str(campaign.external_id),
        adset_external_id=str(groups[0].external_id) if len(groups) == 1 else "",
        end_time=groups[0].end_time if len(groups) == 1 else None,
        spend_cap_minor=campaign.spend_cap_minor,
        currency=_currency(campaign=campaign, groups=groups),
        can_change=check_limit_change(state=state).allowed,
    )


def _currency(*, campaign: Campaign, groups: list[AdSet]) -> str:
    account = getattr(campaign, "ad_account", None)
    for value in (
        campaign.currency,
        next((row.currency for row in groups if row.currency), ""),
        getattr(account, "currency", ""),
    ):
        if value:
            return str(value)
    return ""


def _audience(*, campaign: Campaign, groups: list[AdSet]) -> AudienceTarget | None:
    if len(groups) != 1:
        return None
    group = groups[0]
    stored = group.targeting_raw
    if not isinstance(stored, dict) or not stored:
        return None
    special = any(
        name and name != _NO_CATEGORY for name in campaign.special_ad_categories or ()
    )
    state = ObjectState(
        delivery=str(group.delivery),
        is_learning=bool(group.is_learning),
        daily_budget_minor=group.daily_budget_minor,
    )
    return AudienceTarget(
        external_id=str(group.external_id),
        spec=stored,
        sketch=describe(stored),
        can_change=check_targeting_change(state=state).allowed,
        is_learning=bool(group.is_learning),
        allows_gender=not special,
        min_radius_km=SPECIAL_MIN_RADIUS_KM if special else MIN_RADIUS_KM,
    )


def _budget(*, campaign: Campaign, groups: list[AdSet]) -> BudgetTarget | None:
    if campaign.daily_budget_minor is not None:
        return _target(obj=campaign, level=ManagedLevel.CAMPAIGN)
    if len(groups) != 1 or groups[0].daily_budget_minor is None:
        return None
    return _target(obj=groups[0], level=ManagedLevel.ADSET)


def _target(*, obj: Any, level: str) -> BudgetTarget:
    return BudgetTarget(
        level=level,
        external_id=str(obj.external_id),
        controls=controls_for(target=obj, level=level),
    )


def fresh_preview(
    db: Session, *, owner: User, external_id: str, ad_format: str = PREVIEW_AD_FORMAT
) -> AdPreview | None:
    """The frame for this ad, if it was fetched recently enough to trust."""
    cutoff = utcnow() - timedelta(minutes=PREVIEW_FRESH_MINUTES)
    return db.scalar(
        select(AdPreview).where(
            AdPreview.owner_id == owner.id,
            AdPreview.external_id == external_id,
            AdPreview.ad_format == ad_format,
            AdPreview.fetched_at >= cutoff,
        )
    )


@dataclass(frozen=True, slots=True)
class AdContent:
    """What one advert says, as this product mirrored it."""

    name: str
    message: str
    headline: str
    description: str
    call_to_action: str
    thumbnail_url: str
    kind: str


def ad_content(db: Session, *, owner: User, target: Any) -> AdContent | None:
    """The words and the picture behind one advert, from the mirror."""
    creative_id = str(getattr(target, "creative_external_id", "") or "")
    if not creative_id:
        return None
    creative = db.scalar(
        select(AdCreative).where(
            AdCreative.owner_id == owner.id, AdCreative.external_id == creative_id
        )
    )
    if creative is None:
        return None
    return AdContent(
        name=creative.name,
        message=creative.message,
        headline=creative.headline,
        description=creative.description,
        call_to_action=creative.call_to_action,
        thumbnail_url=creative.thumbnail_url,
        kind=creative.kind,
    )


__all__ = [
    "AdContent",
    "AudienceTarget",
    "BudgetTarget",
    "Editable",
    "LimitsTarget",
    "ad_content",
    "editable",
    "fresh_preview",
]
