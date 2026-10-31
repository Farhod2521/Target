"""The «Kengaytirilgan» tab's answers, each checked against what the goal takes,
and the campaign's own name typed on the card."""

import logging
from dataclasses import dataclass, replace
from datetime import date
from typing import Final

from sitekit import SiteProbe
from sqlalchemy.orm import Session

from app.common.money import format_minor, provider_money
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    ATTRIBUTION,
    BUDGET_AT_ADSET,
    BUDGET_AT_CAMPAIGN,
    BUDGET_LEVEL,
    BUDGET_SHARING,
    CALL_TO_ACTION,
    CAMPAIGN_TYPE,
    CONVERSION_EVENT,
    FREQUENCY_CAP,
    HIGHER_INTENT,
    LAUNCH_NAME_MAX,
    LAUNCH_RELATED_TYPE,
    PIXEL_ID,
    URL_TAGS,
)
from app.modules.ads.exceptions import (
    ButtonLocked,
    ButtonNotOffered,
    CampaignNameTooLong,
    CampaignTypeLocked,
    CampaignTypeNotOffered,
    ConversionEventLocked,
    ConversionEventNotOffered,
    CostCapNotOffered,
    CostCapTooLow,
    DeliveryOptionLocked,
    DeliveryOptionUnusable,
    EndDateLocked,
    EndDateUnusable,
    PixelLocked,
    PixelNotOffered,
    ProposalLocked,
    SpendLimitsLocked,
    SpendLimitsUnusable,
    UrlTagsLocked,
    UrlTagsUnusable,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.naming import campaign_name
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.conversion_event import offered_events
from app.modules.ads.selectors.delivery_options import (
    MAX_CAP_DAYS,
    goal_builds_a_form,
    goal_counts_on_the_site,
    goal_is_seen_rather_than_acted_on,
)
from app.modules.ads.selectors.goals import goal_optimization
from app.modules.ads.selectors.pixel import usable_pixels
from app.modules.ads.selectors.tracking import goal_sends_to_a_site, offered_buttons
from app.modules.ads.services.launch import save_answers
from app.modules.ads.services.targeting import minimum_budget
from app.modules.audit.constants import EventName
from app.modules.businesses.models import Business
from core.targeting import (
    BuiltTargeting,
    accepts_cap,
    attribution_window,
    clean_tags,
    min_daily_for_cap,
    spend_limits_fit,
    tags_are_usable,
    types_for,
)

logger = logging.getLogger(__name__)
BLIND_GOALS: Final[dict[str, str]] = {"LANDING_PAGE_VIEWS": "LINK_CLICKS"}
NO_PIXEL: Final = "no_pixel_clicks"
READ: Final = "ok"


@dataclass(frozen=True, slots=True)
class AdvancedEdit:
    """Everything the «Kengaytirilgan» tab posts, as one answer."""

    campaign_type: str = ""
    conversion_event: str = ""
    pixel_id: str = ""
    call_to_action: str = ""
    url_tags: str = ""
    end_date: date | None = None
    total_cap_minor: int | None = None
    max_result_cost_minor: int | None = None
    attribution: str = ""
    cap_times: int | None = None
    cap_days: int | None = None


@dataclass(frozen=True, slots=True)
class BudgetEdit:
    """What the «Byudjet» tab posts."""

    level: str
    sharing: bool = False


@dataclass(frozen=True, slots=True)
class CreativeEdit:
    position: int
    primary_text: str
    headline: str
    description: str
    ad_name: str = ""


def choose_button(db: Session, *, launch: CampaignLaunch, key: str) -> CampaignLaunch:
    if campaign_type_locked(launch=launch):
        raise ButtonLocked
    if key not in {row.key for row in offered_buttons(db, launch=launch)}:
        raise ButtonNotOffered
    return save_answers(db, launch=launch, **{CALL_TO_ACTION: key})


def choose_campaign_type(
    db: Session, *, launch: CampaignLaunch, key: str
) -> CampaignLaunch:
    if campaign_type_locked(launch=launch):
        raise CampaignTypeLocked
    goal = str(launch.answers.get("goal") or "")
    if key not in {row.key for row in types_for(provider=launch.provider, goal=goal)}:
        raise CampaignTypeNotOffered
    return save_answers(db, launch=launch, **{CAMPAIGN_TYPE: key})


def choose_conversion_event(
    db: Session, *, launch: CampaignLaunch, key: str
) -> CampaignLaunch:
    if campaign_type_locked(launch=launch):
        raise ConversionEventLocked
    if key not in {row.key for row in offered_events(db, launch=launch)}:
        raise ConversionEventNotOffered
    return save_answers(db, launch=launch, **{CONVERSION_EVENT: key})


def choose_cost_cap(
    db: Session, *, launch: CampaignLaunch, amount_minor: int
) -> CampaignLaunch:
    """Keep ``amount_minor`` as the ceiling per result, or clear it with zero."""
    if campaign_type_locked(launch=launch):
        raise SpendLimitsLocked
    if not amount_minor:
        return save_answers(db, launch=launch, max_result_cost_minor=0)
    optimization = goal_optimization(db, launch=launch)
    if not accepts_cap(optimization):
        raise CostCapNotOffered
    needed = max(
        min_daily_for_cap(cap_minor=amount_minor),
        minimum_budget(ad_account=launch.ad_account, optimization_goal=optimization),
    )
    if int(launch.daily_budget_minor or 0) < needed:
        places = provider_money(provider=launch.provider).decimal_places(
            launch.currency
        )
        raise CostCapTooLow(
            needed=format_minor(
                amount_minor=needed, currency=launch.currency, places=places
            )
        )
    return save_answers(db, launch=launch, max_result_cost_minor=amount_minor)


def _unlocked(launch: CampaignLaunch) -> None:
    if campaign_type_locked(launch=launch):
        raise DeliveryOptionLocked


def choose_budget(
    db: Session, *, launch: CampaignLaunch, level: str, sharing: bool
) -> CampaignLaunch:
    """Where the daily budget lives. Sharing belongs to groups, so it needs them."""
    _unlocked(launch)
    if level not in (BUDGET_AT_CAMPAIGN, BUDGET_AT_ADSET):
        raise DeliveryOptionUnusable
    if sharing and level != BUDGET_AT_ADSET:
        raise DeliveryOptionUnusable
    return save_answers(db, launch=launch, **{BUDGET_LEVEL: level, BUDGET_SHARING: sharing})


def choose_attribution(
    db: Session, *, launch: CampaignLaunch, key: str
) -> CampaignLaunch:
    _unlocked(launch)
    if key and attribution_window(provider=launch.provider, key=key) is None:
        raise DeliveryOptionUnusable
    if key and not goal_counts_on_the_site(db, launch=launch):
        raise DeliveryOptionUnusable
    return save_answers(db, launch=launch, **{ATTRIBUTION: key})


def choose_frequency_cap(
    db: Session, *, launch: CampaignLaunch, times: int | None, days: int | None
) -> CampaignLaunch:
    _unlocked(launch)
    if not times or not days:
        return save_answers(db, launch=launch, **{FREQUENCY_CAP: []})
    if not goal_is_seen_rather_than_acted_on(db, launch=launch):
        raise DeliveryOptionUnusable
    if times < 1 or days < 1 or days > MAX_CAP_DAYS:
        raise DeliveryOptionUnusable
    return save_answers(db, launch=launch, **{FREQUENCY_CAP: [times, days]})


def choose_form_intent(
    db: Session, *, launch: CampaignLaunch, higher: bool
) -> CampaignLaunch:
    _unlocked(launch)
    if higher and not goal_builds_a_form(db, launch=launch):
        raise DeliveryOptionUnusable
    return save_answers(db, launch=launch, **{HIGHER_INTENT: higher})


def choose_end_date(
    db: Session, *, launch: CampaignLaunch, day: date | None, today: date
) -> CampaignLaunch:
    if campaign_type_locked(launch=launch):
        raise EndDateLocked
    if day is not None and day <= max(today, launch.start_date or today):
        raise EndDateUnusable
    return save_answers(db, launch=launch, end_date=day.isoformat() if day else "")


def choose_pixel(
    db: Session, *, launch: CampaignLaunch, external_id: str
) -> CampaignLaunch:
    if campaign_type_locked(launch=launch):
        raise PixelLocked
    if external_id not in {row.external_id for row in usable_pixels(db, launch=launch)}:
        raise PixelNotOffered
    return save_answers(db, launch=launch, **{PIXEL_ID: external_id})


def choose_spend_limits(
    db: Session, *, launch: CampaignLaunch, total_minor: int | None
) -> CampaignLaunch:
    if campaign_type_locked(launch=launch):
        raise SpendLimitsLocked
    refused = spend_limits_fit(
        daily_minor=int(launch.daily_budget_minor or 0),
        total_cap_minor=int(total_minor or 0),
    )
    if refused:
        raise SpendLimitsUnusable(reason=refused)
    return save_answers(db, launch=launch, total_cap_minor=total_minor or 0)


def choose_url_tags(
    db: Session, *, launch: CampaignLaunch, tags: str
) -> CampaignLaunch:
    if campaign_type_locked(launch=launch):
        raise UrlTagsLocked
    if not goal_sends_to_a_site(db, launch=launch) or not tags_are_usable(tags):
        raise UrlTagsUnusable
    return save_answers(db, launch=launch, **{URL_TAGS: clean_tags(tags)})


def rename_campaign(
    db: Session, *, launch: CampaignLaunch, business: Business, name: str
) -> None:
    """Store the owner's name for the campaign, or go back to the generated one."""
    from app.modules.audit.services import emit

    if campaign_type_locked(launch=launch):
        raise ProposalLocked
    wanted = name.strip()
    if len(wanted) > LAUNCH_NAME_MAX:
        raise CampaignNameTooLong(limit=LAUNCH_NAME_MAX)
    if wanted == campaign_name(launch=launch, business=business):
        wanted = ""
    if wanted == launch.campaign_name:
        return
    previous = launch.campaign_name
    launch.campaign_name = wanted
    db.flush()
    emit(
        db,
        owner_id=launch.owner_id,
        name=EventName.LAUNCH_RENAMED,
        aggregate_type=LAUNCH_RELATED_TYPE,
        aggregate_id=launch.id,
        payload={"previous": previous, "name": wanted},
    )


def without_blind_goal(
    db: Session, *, launch: CampaignLaunch, built: BuiltTargeting, site: SiteProbe
) -> BuiltTargeting:
    """The spec to send, bought for clicks when the page has no pixel."""
    swap = BLIND_GOALS.get(built.optimization_goal)
    if swap is None or site.outcome != READ:
        return built
    if site.meta_pixel_ids or site.has_tag_manager:
        return built
    logger.info(
        "launch %s: no pixel on %s, optimising for %s instead of %s",
        launch.id,
        site.final_url or site.url,
        swap,
        built.optimization_goal,
    )
    draft_field.set_launch_note(fresh(launch, "draft"), NO_PIXEL)
    db.commit()
    return replace(built, optimization_goal=swap)
