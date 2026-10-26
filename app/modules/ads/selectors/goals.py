"""What the answered goal implies, read off the catalogue."""

from sqlalchemy.orm import Session

from app.common.presets import goals_for, offered_goals
from app.modules.ads.constants import LEGACY_PLAN_DESTINATIONS, ChatChannel
from app.modules.ads.models import CampaignLaunch
from app.modules.businesses.models import Business
from core.targeting import DEFAULT_CHAT_CHANNEL, Preset, campaign_type


def legacy_plan_goals(*, provider: str, category: str) -> tuple[Preset, ...]:
    """The goals the first step without the three questions offers."""
    return tuple(
        preset
        for preset in offered_goals(provider=provider, category=category)
        if preset.sends_to in LEGACY_PLAN_DESTINATIONS
    )


def destination_link(*, launch: CampaignLaunch, business: Business) -> str:
    """The address this campaign's ad points at, if it points at one."""
    answered = str(launch.answers.get("link_url") or "").strip()
    return answered or str(business.website or "").strip()


def launch_category(db: Session, *, launch: CampaignLaunch) -> str:
    from app.modules.businesses.selectors import business_for_page

    business = business_for_page(db, owner=launch.owner, page=launch.page)
    return business.category if business is not None else ""


def goal_preset(
    db: Session, *, launch: CampaignLaunch, goal: str = ""
) -> Preset | None:
    """The catalogue entry behind the goal this launch answered."""
    chosen = goal or str(launch.answers.get("goal", ""))
    if not chosen:
        return None
    category = launch_category(db, launch=launch)
    if not category:
        return None
    for preset in goals_for(provider=launch.provider, category=category):
        if preset.goal == chosen:
            return preset
    return None


def goal_optimization(db: Session, *, launch: CampaignLaunch, goal: str = "") -> str:
    """What the chosen goal optimises toward, in the provider's word."""
    from app.modules.ads.selectors.campaign_type import chosen_campaign_type

    preset = goal_preset(db, launch=launch, goal=goal)
    if preset is None:
        return ""
    chosen = campaign_type(
        provider=launch.provider,
        goal=preset.goal,
        key=chosen_campaign_type(launch=launch),
    )
    return chosen.optimization_goal if chosen else preset.optimization_goal


def goal_objective(db: Session, *, launch: CampaignLaunch) -> str:
    """The campaign objective this launch will be built under."""
    from app.modules.ads.selectors.campaign_type import chosen_campaign_type

    preset = goal_preset(db, launch=launch)
    if preset is None:
        return ""
    chosen = campaign_type(
        provider=launch.provider,
        goal=preset.goal,
        key=chosen_campaign_type(launch=launch),
    )
    return chosen.objective if chosen else preset.objective


def goal_opens_chat(db: Session, *, launch: CampaignLaunch, goal: str = "") -> bool:
    preset = goal_preset(db, launch=launch, goal=goal)
    return preset is not None and preset.opens_chat


def chat_channels(
    db: Session, *, launch: CampaignLaunch, goal: str = ""
) -> tuple[str, ...]:
    """The messaging surfaces this owner's page can actually open."""
    from app.modules.ads.selectors.launch_page import launch_page

    if not goal_opens_chat(db, launch=launch, goal=goal):
        return ()
    page = launch_page(db, launch=launch)
    if page is not None and page.has_instagram:
        return (ChatChannel.MESSENGER, ChatChannel.INSTAGRAM)
    return (ChatChannel.MESSENGER,)


def chosen_channel(*, launch: CampaignLaunch) -> str:
    answered = str(launch.answers.get("chat_channel") or "")
    return answered or DEFAULT_CHAT_CHANNEL


def opening_channel(db: Session, *, launch: CampaignLaunch, goal: str = "") -> str:
    """Which surface the picker opens on before anybody has touched it."""
    answered = str(launch.answers.get("chat_channel") or "")
    if answered:
        return answered
    if ChatChannel.INSTAGRAM in chat_channels(db, launch=launch, goal=goal):
        return ChatChannel.INSTAGRAM
    return DEFAULT_CHAT_CHANNEL


def goal_needs_link(db: Session, *, launch: CampaignLaunch, goal: str = "") -> bool:
    preset = goal_preset(db, launch=launch, goal=goal)
    return preset is not None and preset.needs_link


def goal_needs_pixel(db: Session, *, launch: CampaignLaunch, goal: str = "") -> bool:
    preset = goal_preset(db, launch=launch, goal=goal)
    return preset is not None and preset.needs_conversion_source


def goal_needs_form(db: Session, *, launch: CampaignLaunch, goal: str = "") -> bool:
    preset = goal_preset(db, launch=launch, goal=goal)
    return preset is not None and preset.needs_lead_form


def goal_needs_phone(db: Session, *, launch: CampaignLaunch, goal: str = "") -> bool:
    preset = goal_preset(db, launch=launch, goal=goal)
    return preset is not None and preset.needs_phone
