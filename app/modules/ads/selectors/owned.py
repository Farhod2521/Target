"""What this product launched: who paid for which page, which campaign a pair holds,
which shared campaign its owner switched off, the open stops, and the ad just started."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from metaads.writing import is_dry_run_id
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.common.money import format_minor, provider_money
from app.common.presets import goal_label
from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import LaunchStatus, LaunchStep
from app.modules.ads.models import (
    AdSet,
    Campaign,
    CampaignLaunch,
    DeliveryStop,
    GoalCampaign,
)
from app.modules.integrations.models import AdAccount

PAUSED_STATUS = "PAUSED"


def launched_payers(db: Session, *, owner: User) -> dict[object, AdAccount]:
    """``{page id: the ad account its newest created launch was paid from}``."""
    found: dict[object, AdAccount] = {}
    for launch in db.scalars(
        select(CampaignLaunch)
        .where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.status == str(LaunchStatus.CREATED),
            CampaignLaunch.page_id.is_not(None),
        )
        .options(selectinload(CampaignLaunch.ad_account))
        .order_by(CampaignLaunch.created_at.desc())
    ):
        found.setdefault(launch.page_id, launch.ad_account)
    return found


@dataclass(frozen=True, slots=True)
class PairCampaigns:
    exact: frozenset[str] = frozenset()
    pageless: frozenset[str] = frozenset()


def campaigns_by_pair(
    db: Session, *, owner: User, pairs: Sequence[Any]
) -> dict[str, PairCampaigns]:
    """``{pair key: its campaigns}`` for every one of ``pairs``. Two queries."""
    accounts = {pair.account.id for pair in pairs}
    if not accounts:
        return {}
    exact: dict[tuple[object, object], set[str]] = defaultdict(set)
    pageless: dict[object, set[str]] = defaultdict(set)
    for created_refs, page, account in db.execute(
        select(
            CampaignLaunch.created_refs,
            CampaignLaunch.page_id,
            CampaignLaunch.ad_account_id,
        ).where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.ad_account_id.in_(accounts),
        )
    ):
        ids = ref_field.ref_ids(created_refs or {}, LaunchStep.CAMPAIGN)
        if page is None:
            pageless[account].update(ids)
        else:
            exact[page, account].update(ids)
    for external_id, page, account in db.execute(
        select(
            GoalCampaign.external_id, GoalCampaign.page_id, GoalCampaign.ad_account_id
        ).where(
            GoalCampaign.owner_id == owner.id,
            GoalCampaign.ad_account_id.in_(accounts),
            GoalCampaign.external_id != "",
        )
    ):
        exact[page, account].add(external_id)
    return {
        pair.key: PairCampaigns(
            exact=_real(exact[pair.page.id, pair.account.id]),
            pageless=_real(pageless[pair.account.id]),
        )
        for pair in pairs
    }


def _real(ids: Iterable[str]) -> frozenset[str]:
    return frozenset(
        external_id for external_id in ids if not is_dry_run_id(external_id)
    )


def owner_paused_campaign(db: Session, *, launch: CampaignLaunch) -> str:
    """The id of the shared campaign the owner switched off, or ``""``."""
    if launch.goal_campaign_id is None:
        return ""
    campaign_id = ref_field.first_id(launch.created_refs or {}, LaunchStep.CAMPAIGN)
    if not campaign_id:
        return ""
    paused = db.scalar(
        select(Campaign.id).where(
            Campaign.owner_id == launch.owner_id,
            Campaign.external_id == campaign_id,
            Campaign.status == PAUSED_STATUS,
        )
    )
    if paused is None:
        return ""
    own = set(ref_field.ref_ids(launch.created_refs or {}, LaunchStep.ADSET))
    others = db.scalar(
        select(AdSet.id)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(
            AdSet.owner_id == launch.owner_id,
            Campaign.external_id == campaign_id,
            AdSet.external_id.not_in(own) if own else AdSet.external_id.is_not(None),
        )
        .limit(1)
    )
    return campaign_id if others is not None else ""


def open_stops(
    db: Session, *, owner: User, accounts: Sequence[AdAccount] | None = None
) -> list[DeliveryStop]:
    """Every open stop, newest first - on these accounts, or on all of them."""
    query = select(DeliveryStop).where(
        DeliveryStop.owner_id == owner.id, DeliveryStop.cleared_at.is_(None)
    )
    if accounts is not None:
        query = query.where(DeliveryStop.ad_account_id.in_([a.id for a in accounts]))
    return list(
        db.scalars(
            query.options(selectinload(DeliveryStop.ad_account)).order_by(
                DeliveryStop.detected_at.desc()
            )
        )
    )


def stop_campaigns(
    db: Session, *, owner: User, stops: Sequence[DeliveryStop]
) -> dict[str, str]:
    wanted = {stop.campaign_external_id for stop in stops if stop.campaign_external_id}
    if not wanted:
        return {}
    return {
        external_id: str(pk)
        for external_id, pk in db.execute(
            select(Campaign.external_id, Campaign.id).where(
                Campaign.owner_id == owner.id, Campaign.external_id.in_(wanted)
            )
        )
    }


@dataclass(frozen=True, slots=True)
class StartedAd:
    business: str
    goal: str
    budget: str
    refs: frozenset[str]
    first: bool


def started_ad(db: Session, *, owner: User, launch_id: str) -> StartedAd | None:
    """The ad this session has just switched on, or ``None``."""
    from app.modules.ads.selectors.goals import goal_preset
    from app.modules.ads.selectors.launches import launch_for
    from app.modules.businesses.selectors import business_for_page

    try:
        pk = UUID(launch_id)
    except (AttributeError, ValueError):
        return None
    launch = launch_for(db, owner=owner, launch_id=pk)
    if launch is None or launch.delivery_started_at is None:
        return None
    business = business_for_page(db, owner=owner, page=launch.page)
    preset = goal_preset(db, launch=launch)
    earlier = db.scalar(
        select(CampaignLaunch.id)
        .where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.delivery_started_at.is_not(None),
            CampaignLaunch.id != launch.id,
        )
        .limit(1)
    )
    return StartedAd(
        business=business.name if business is not None else "",
        goal=goal_label(preset=preset)
        if preset is not None
        else str(launch.answers.get("goal", "")),
        budget=format_minor(
            amount_minor=launch.daily_budget_minor,
            currency=launch.currency,
            places=provider_money(provider=launch.provider).decimal_places(
                launch.currency
            ),
        ),
        refs=_refs(launch),
        first=earlier is None,
    )


def _refs(launch: CampaignLaunch) -> frozenset[str]:
    found: set[str] = set()
    for value in (launch.created_refs or {}).values():
        items = value if isinstance(value, list) else [value]
        found.update(str(item) for item in items)
    return frozenset(found)
