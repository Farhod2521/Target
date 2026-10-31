"""The proposal, translated into the objects Meta wants: the campaign, the ad set,
the creative, the lead form and the button."""

from typing import Any, Final

from metaads.boosts import BoostSpec
from metaads.specs import (
    BID_COST_CAP,
    BID_LOWEST_COST,
    THANK_YOU_CALL,
    THANK_YOU_NONE,
    THANK_YOU_WEBSITE,
    CampaignSpec,
    CarouselCard,
    CreativeSpec,
    LeadFormSpec,
    LeadQuestionSpec,
    instagram_profile_url,
    is_external,
)
from metaads.specs import AdSetSpec as MetaAdSetSpec

from app.common.config import settings
from app.modules.ads import draft as draft_field
from app.modules.ads import naming
from app.modules.ads.constants import (
    CUSTOM,
    HIGHER_INTENT,
    QUESTION_TYPES,
    DraftSection,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative
from app.modules.ads.selectors.budget_level import (
    campaign_budget_minor,
    held_by_campaign,
    shares_budget,
)
from app.modules.ads.selectors.lead_form import (
    default_title,
    effective_ending,
    privacy_url,
)
from app.modules.ads.selectors.schedule import effective_campaign_name
from app.modules.businesses.models import Business
from core.leads import TYPED_KEYS
from core.leads.ending import (
    ENDING_CALL,
    ENDING_TELEGRAM,
    ENDING_WEBSITE,
    FormEnding,
    telegram_url,
)
from core.targeting import BuiltTargeting

PAGE_DESTINATIONS: Final[frozenset[str]] = frozenset(
    {"ON_AD", "MESSENGER", "INSTAGRAM_DIRECT", "WHATSAPP", "INSTAGRAM_PROFILE"}
)
CALL_DESTINATION: Final = "PHONE_CALL"
CALL_PAGE_OBJECTIVES: Final[frozenset[str]] = frozenset(
    {"OUTCOME_LEADS", "OUTCOME_ENGAGEMENT"}
)
CLICK_THROUGH: Final = "CLICK_THROUGH"
VIEW_THROUGH: Final = "VIEW_THROUGH"
IMPRESSION_EVENT: Final = "IMPRESSIONS"
AWARENESS_OBJECTIVE: Final = "OUTCOME_AWARENESS"
AWARENESS_PAGE_GOALS: Final[frozenset[str]] = frozenset(
    {"AD_RECALL_LIFT", "REACH", "IMPRESSIONS"}
)
CHAT_DESTINATIONS: Final[frozenset[str]] = frozenset(
    {"MESSENGER", "INSTAGRAM_DIRECT", "WHATSAPP"}
)
INSTAGRAM_DIRECT: Final = "INSTAGRAM_DIRECT"
INSTAGRAM_PROFILE: Final = "INSTAGRAM_PROFILE"
INSTAGRAM_DESTINATIONS: Final[frozenset[str]] = frozenset(
    {INSTAGRAM_DIRECT, INSTAGRAM_PROFILE}
)


def campaign_spec(
    *, launch: CampaignLaunch, business: Business, built: BuiltTargeting
) -> CampaignSpec:
    return CampaignSpec(
        name=effective_campaign_name(launch=launch, business=business),
        objective=built.objective,
        special_ad_categories=built.special_ad_categories,
        special_ad_category_country=built.special_ad_category_countries,
        spend_cap_minor=int(built.total_cap_minor or 0),
    )


def goal_campaign_spec(
    *, launch: CampaignLaunch, business: Business, built: BuiltTargeting, number: int
) -> CampaignSpec:
    """The campaign a page's launches for one goal share, paused."""
    sharing = shares_budget(launch=launch)
    budget = campaign_budget_minor(launch=launch)
    return CampaignSpec(
        name=naming.goal_campaign_name(launch=launch, business=business, number=number),
        objective=built.objective,
        special_ad_categories=built.special_ad_categories,
        special_ad_category_country=built.special_ad_category_countries,
        budget_sharing=sharing,
        daily_budget_minor=budget or 0,
        bid_strategy=_strategy(built) if budget or sharing else "",
    )


def adset_spec(
    *,
    launch: CampaignLaunch,
    business: Business,
    built: BuiltTargeting,
    campaign_id: str,
    page_id: str = "",
    start_time: str = "",
    end_time: str = "",
    name: str = "",
    daily_budget_minor: int | None = None,
) -> MetaAdSetSpec:
    """The audience and, unless the campaign holds it, the money."""
    money = (
        int(launch.daily_budget_minor or 0)
        if daily_budget_minor is None
        else int(daily_budget_minor)
    )
    if held_by_campaign(launch=launch):
        money = 0
    return MetaAdSetSpec(
        name=name or naming.adset_name(launch=launch, business=business),
        campaign_id=campaign_id,
        daily_budget_minor=money,
        optimization_goal=built.optimization_goal,
        billing_event=built.billing_event,
        destination_type=built.destination_type,
        targeting=dict(launch.targeting or {}),
        promoted_object=_promoted(built=built, page_id=page_id),
        start_time=start_time,
        end_time=end_time,
        bid_strategy=_strategy(built),
        bid_amount_minor=_cap(built),
        attribution=_attribution(built),
        frequency_control=_frequency(built),
    )


def _strategy(built: BuiltTargeting) -> str:
    return BID_COST_CAP if _cap(built) else BID_LOWEST_COST


def _attribution(built: BuiltTargeting) -> tuple[dict[str, object], ...]:
    days = built.attribution_days
    if days is None:
        return ()
    clicks, views = days
    spec: list[dict[str, object]] = [
        {"event_type": CLICK_THROUGH, "window_days": clicks}
    ]
    if views:
        spec.append({"event_type": VIEW_THROUGH, "window_days": views})
    return tuple(spec)


def _frequency(built: BuiltTargeting) -> tuple[dict[str, object], ...]:
    if built.frequency_cap is None:
        return ()
    times, days = built.frequency_cap
    return ({"event": IMPRESSION_EVENT, "interval_days": days, "max_frequency": times},)


def _cap(built: BuiltTargeting) -> int:
    return int(built.max_result_cost_minor or 0)


def _promoted(*, built: BuiltTargeting, page_id: str) -> dict[str, object]:
    promoted: dict[str, object] = dict(built.promoted_object)
    if page_id and _names_the_page(built):
        promoted.setdefault("page_id", page_id)
    return promoted


def _names_the_page(built: BuiltTargeting) -> bool:
    if built.destination_type == CALL_DESTINATION:
        return built.objective in CALL_PAGE_OBJECTIVES
    if built.destination_type in PAGE_DESTINATIONS:
        return True
    return (
        built.objective == AWARENESS_OBJECTIVE
        and built.optimization_goal in AWARENESS_PAGE_GOALS
    )


def creative_spec(
    *,
    launch: CampaignLaunch,
    business: Business,
    built: BuiltTargeting,
    variant: LaunchCreative,
    page_id: str,
    instagram_id: str = "",
    instagram_username: str = "",
    form_id: str = "",
    image_hash: str = "",
    video_id: str = "",
    thumbnail_url: str = "",
    cards: tuple[CarouselCard, ...] = (),
) -> CreativeSpec:
    """The words the owner approved, around the picture they chose."""
    return CreativeSpec(
        name=naming.creative_name(
            launch=launch, business=business, position=variant.position
        ),
        page_id=page_id,
        link_url=destination(
            launch=launch,
            business=business,
            built=built,
            page_id=page_id,
            instagram_username=instagram_username,
        ),
        message=variant.primary_text,
        headline=variant.headline,
        description=variant.description,
        image_hash=image_hash,
        video_id=video_id,
        thumbnail_url=thumbnail_url,
        cards=cards,
        lead_form_id=form_id,
        call_to_action=built.call_to_action,
        app_destination=app_destination(built),
        phone_number=phone_number(built),
        instagram_user_id=instagram_user(built=built, instagram_id=instagram_id),
        welcome_text=built.welcome_text,
        autofill_text=built.autofill_text,
        welcome_questions=built.welcome_questions,
        url_tags=built.url_tags,
    )


def boost_spec(
    *,
    launch: CampaignLaunch,
    business: Business,
    built: BuiltTargeting,
    variant: LaunchCreative,
    page_id: str,
    instagram_id: str,
    instagram_username: str = "",
    form_id: str = "",
) -> BoostSpec:
    """The same ad, made out of a post that is already on the profile."""
    asset = variant.media_asset
    return BoostSpec(
        name=naming.creative_name(
            launch=launch, business=business, position=variant.position
        ),
        page_id=page_id,
        instagram_user_id=instagram_id,
        media_id=asset.external_id if asset is not None else "",
        call_to_action=built.call_to_action,
        lead_form_id=form_id,
        app_destination=app_destination(built),
        link_url=destination(
            launch=launch,
            business=business,
            built=built,
            page_id=page_id,
            instagram_username=instagram_username,
        ),
        url_tags=built.url_tags,
        welcome_text=built.welcome_text,
        autofill_text=built.autofill_text,
        welcome_questions=built.welcome_questions,
    )


# -- the button ------------------------------------------------------------------------


def instagram_user(*, built: BuiltTargeting, instagram_id: str) -> str:
    if built.destination_type not in INSTAGRAM_DESTINATIONS:
        return ""
    return instagram_id


def app_destination(built: BuiltTargeting) -> str:
    if not built.opens_chat or built.destination_type not in CHAT_DESTINATIONS:
        return ""
    return built.destination_type


def phone_number(built: BuiltTargeting) -> str:
    return built.phone_number if built.needs_phone else ""


def destination(
    *,
    launch: CampaignLaunch,
    business: Business,
    built: BuiltTargeting,
    page_id: str,
    instagram_username: str = "",
) -> str:
    """Where the ad's link points."""
    if built.needs_link:
        return built.link_url
    if built.opens_profile:
        return instagram_profile_url(instagram_username)
    site = str(launch.answers.get("link_url") or business.website or "").strip()
    if site and is_external(site):
        return site
    if not built.shows_a_button:
        return _own_address(page_id=page_id, instagram_username=instagram_username)
    return str(settings.default_ad_link)


def _own_address(*, page_id: str, instagram_username: str) -> str:
    if instagram_username.strip().removeprefix("@").strip("/"):
        return instagram_profile_url(instagram_username)
    return f"https://www.facebook.com/{page_id}"


# -- the lead form ---------------------------------------------------------------------


def form_spec(
    *, launch: CampaignLaunch, business: Business, attempt: int = 1
) -> LeadFormSpec:
    """The form itself, and the promise Meta requires beside it."""
    ending = effective_ending(launch=launch, business=business).ending
    return LeadFormSpec(
        name=naming.form_name(launch=launch, business=business, attempt=attempt),
        privacy_policy_url=privacy_url(business),
        questions=_questions(launch),
        thank_you_title=ending.title or default_title(business),
        thank_you_body=ending.body,
        **_button(ending, business=business),
        higher_intent=bool(launch.answers.get(HIGHER_INTENT)),
    )


def _questions(launch: CampaignLaunch) -> tuple[LeadQuestionSpec, ...]:
    chosen = draft_field.with_phone(
        draft_field.chosen(launch.draft, DraftSection.FORM) or []
    )
    keys = _contact_keys(chosen)
    return tuple(
        LeadQuestionSpec(
            kind=QUESTION_TYPES.get(str(item.get("kind", "")), CUSTOM),
            label=str(item.get("label", "")),
            options=tuple(str(option) for option in item.get("options") or ()),
            key=keys.get(index, ""),
        )
        for index, item in enumerate(chosen)
    )


def _contact_keys(questions: list[dict[str, Any]]) -> dict[int, str]:
    """The key each typed name, phone or email question is sent under.

    Its answer then lands in the lead's own column instead of arriving as
    ``q1``. The first question of each kind only: a key appears once on a
    form, and a second one is another answer to keep, not the column.
    """
    keys: dict[int, str] = {}
    taken: set[str] = set()
    for index, item in enumerate(questions):
        kind = draft_field.typed_contact(item)
        if kind and kind not in taken:
            taken.add(kind)
            keys[index] = TYPED_KEYS[kind]
    return keys


def _button(ending: FormEnding, *, business: Business) -> dict[str, str]:
    if ending.kind in (ENDING_WEBSITE, ENDING_TELEGRAM):
        return {
            "thank_you_button": THANK_YOU_WEBSITE,
            "thank_you_button_text": ending.words,
            "thank_you_url": telegram_url(ending.target)
            if ending.kind == ENDING_TELEGRAM
            else ending.target,
        }
    if ending.kind == ENDING_CALL:
        return {
            "thank_you_button": THANK_YOU_CALL,
            "thank_you_button_text": ending.words,
            "thank_you_phone": ending.target,
            "thank_you_country": business.country_code.upper(),
        }
    return {"thank_you_button": THANK_YOU_NONE}
