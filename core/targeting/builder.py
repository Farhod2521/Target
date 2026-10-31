"""Answers plus a preset, in - a targeting spec, out."""

from collections.abc import Mapping
from typing import Any, Final, cast

from adskit import MinorUnits

from core.targeting.adjustments import Adjustment, AdjustmentReason
from core.targeting.attribution import attribution_window, takes_attribution
from core.targeting.audiences import AudienceChoice
from core.targeting.budget import FREQUENCY_GOALS, accepts_cap, spend_limits_fit
from core.targeting.buttons import button
from core.targeting.campaign_types import campaign_type
from core.targeting.compat import needs_pixel
from core.targeting.contracts import (
    BuiltTargeting,
    BusinessProfile,
    ConversionSource,
    Interest,
    OnboardingAnswers,
    QualityLeads,
)
from core.targeting.conversion_events import (
    EVENT_KEY,
    conversion_event,
    events_for,
)
from core.targeting.destinations import AdDestination, needs_link
from core.targeting.destinations import channel as chat_channel
from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import GeoChoice, geo_locations
from core.targeting.modes import TargetingMode, wants_interests
from core.targeting.placements import keep_chat_reachable, pin_to_instagram
from core.targeting.presets import Preset, PresetCatalog
from core.targeting.quality import QUALITY_GOAL
from core.targeting.quality import goal_for as quality_goal
from core.targeting.render import render
from core.targeting.tracking import clean_tags, tags_are_usable
from core.targeting.validators import validate_structure


def build(
    *,
    provider: str,
    answers: OnboardingAnswers,
    business: BusinessProfile,
    catalog: PresetCatalog,
    currency: str,
    min_daily_minor: int = 0,
    geo: GeoChoice | None = None,
    conversion: ConversionSource | None = None,
    quality: QualityLeads | None = None,
    audiences: AudienceChoice | None = None,
    link: str = "",
    welcome: str = "",
    questions: tuple[str, ...] = (),
    phone: str = "",
) -> BuiltTargeting:
    """The spec for one campaign, ready to be reviewed or sent."""
    preset = catalog.find(
        provider=provider, category=answers.category, goal=answers.goal
    )
    kind = campaign_type(provider=provider, goal=preset.goal, key=answers.campaign_type)
    objective = kind.objective if kind else preset.objective
    kind_goal = kind.optimization_goal if kind else preset.optimization_goal

    template: dict[str, Any] = dict(preset.targeting)
    notes: list[Adjustment] = []
    if geo is not None:
        template["geo_locations"] = geo_locations(geo)
        if geo.widened:
            notes.append(
                Adjustment(field="geo_locations", reason="location_missing", detail="")
            )

    spec: dict[str, Any] = render(
        template,
        sources={"business": business, "answers": answers},
        defaults=preset.defaults,
    )

    total_cap, limit_notes = _total_cap(answers)
    promoted, promotion_notes = _promoted_object(
        provider=provider,
        objective=objective,
        preset=preset,
        business=business,
        answers=answers,
        conversion=conversion,
    )
    notes.extend(promotion_notes)

    mode, mode_notes = _mode(business=business, answers=answers)
    notes.extend(mode_notes)

    chosen_audiences = audiences or AudienceChoice()

    confirmed = tuple(i for i in answers.interests if i.is_confirmed)
    if confirmed and wants_interests(mode):
        spec["flexible_spec"] = [_detailed(confirmed)]

    checked, checks = validate_structure(
        spec,
        special_ad_category=business.special_ad_category,
        daily_budget_minor=int(answers.daily_budget_minor),
        min_daily_minor=min_daily_minor,
        currency=currency,
        targeting_mode=mode,
        placement_mode=answers.placement_mode,
        placement_positions=answers.placement_positions,
        audiences=chosen_audiences,
    )
    if preset.opens_profile:
        pin_to_instagram(checked, notes)
    elif preset.opens_chat:
        keep_chat_reachable(
            checked, notes, mode=answers.placement_mode, chat=answers.chat_channel
        )

    surface = chat_channel(answers.chat_channel)

    cap, cap_notes = _cost_cap(answers=answers, goal_of=kind_goal)
    notes.extend(cap_notes)
    notes.extend(limit_notes)

    wanted = quality or QualityLeads()
    goal = quality_goal(
        preset_goal=kind_goal,
        chosen=wanted.chosen,
        reporting=wanted.is_reporting,
        qualified_recently=wanted.qualified_recently,
    )

    return BuiltTargeting(
        objective=objective,
        optimization_goal=goal,
        billing_event=preset.billing_event,
        destination_type=(
            surface.destination_type if preset.opens_chat else preset.destination_type
        ),
        targeting=checked,
        daily_budget_minor=MinorUnits(int(answers.daily_budget_minor)),
        sends_to=preset.sends_to,
        call_to_action=_button(
            answers.call_to_action,
            provider=provider,
            sends_to=preset.sends_to,
            preset_word=(
                surface.call_to_action if preset.opens_chat else preset.call_to_action
            ),
        ),
        link_url=link,
        url_tags=_tags(answers.url_tags, sends_to=preset.sends_to),
        phone_number=phone,
        campaign_type=kind.key if kind else "",
        welcome_text=welcome,
        autofill_text=preset.autofill_message,
        welcome_questions=questions if welcome and preset.opens_chat else (),
        currency=currency,
        special_ad_categories=_categories(business),
        special_ad_category_countries=_category_countries(
            business=business, targeting=spec, geo=geo
        ),
        preset_key=preset.key,
        preset_version=preset.version,
        targeting_mode=mode,
        placement_mode=answers.placement_mode,
        audiences=chosen_audiences,
        max_result_cost_minor=cap,
        attribution_days=(
            _window(answers.attribution_key, provider=provider)
            if takes_attribution(goal)
            else None
        ),
        frequency_cap=(answers.frequency_cap if goal in FREQUENCY_GOALS else None),
        total_cap_minor=total_cap,
        promoted_object=_quality_promotion(promoted, upgraded=goal),
        needs_conversion_source=(
            needs_pixel(provider=provider, key=kind.key)
            if kind
            else preset.needs_conversion_source
        ),
        buys_qualified_leads=goal != kind_goal,
        adjustments=(
            *notes,
            *checks,
            *(_unconfirmed(answers.interests) if wants_interests(mode) else ()),
        ),
    )


def _mode(
    *, business: BusinessProfile, answers: OnboardingAnswers
) -> tuple[TargetingMode, list[Adjustment]]:
    """Which mode this spec is built as, after the law has had its say."""
    if not business.special_ad_category:
        return answers.targeting_mode, []
    if answers.targeting_mode == "interests":
        return "interests", []
    return "interests", [
        Adjustment(
            field="targeting_automation",
            reason="special_ad_category",
            detail=business.special_ad_category,
        )
    ]


def _promoted_object(
    *,
    provider: str,
    objective: str,
    preset: Preset,
    business: BusinessProfile,
    answers: OnboardingAnswers,
    conversion: ConversionSource | None,
) -> tuple[dict[str, Any], list[Adjustment]]:
    """The off-site event this ad set optimises towards, if there is one."""
    if not preset.needs_conversion_source:
        return {}, []

    if conversion is None or not conversion.is_usable:
        return {}, [
            Adjustment(
                field="promoted_object",
                reason="conversion_source_missing",
                detail=preset.goal,
            )
        ]

    rendered: dict[str, Any] = render(
        dict(preset.promoted_object),
        sources={"business": business, "answers": answers, "conversion": conversion},
        defaults=preset.defaults,
    )
    return (
        _counted_event(
            rendered,
            provider=provider,
            objective=objective,
            chosen=answers.conversion_event,
        ),
        [],
    )


def _counted_event(
    promoted: dict[str, Any], *, provider: str, objective: str, chosen: str
) -> dict[str, Any]:
    """The event this ad set is bought against, once the owner has had a say."""
    if not chosen or EVENT_KEY not in promoted:
        return promoted
    known = conversion_event(provider=provider, key=chosen)
    if known is None or known not in events_for(provider=provider, objective=objective):
        return promoted
    return dict(promoted) | {EVENT_KEY: known.key}


def _button(
    given: str, *, provider: str, sends_to: AdDestination, preset_word: str
) -> str:
    """The word on the button, once the provider has had a say."""
    if not given or sends_to == "chat":
        return preset_word
    chosen = button(provider=provider, sends_to=sends_to, key=given)
    return chosen.key if chosen is not None else preset_word


def _window(key: str, *, provider: str) -> tuple[int, int] | None:
    """The chosen window as a pair of day counts, or ``None`` for the default."""
    if not key:
        return None
    found = attribution_window(provider=provider, key=key)
    return None if found is None else (found.click_days, found.view_days)


def _total_cap(
    answers: OnboardingAnswers,
) -> tuple[MinorUnits | None, list[Adjustment]]:
    """The total ceiling, or none, with a note when it is dropped."""
    total = answers.total_cap_minor
    if not total:
        return None, []
    refused = spend_limits_fit(
        daily_minor=int(answers.daily_budget_minor), total_cap_minor=int(total)
    )
    if refused:
        return None, [
            Adjustment(
                field="spend_limits",
                reason=cast(AdjustmentReason, refused),
                detail="",
            )
        ]
    return total, []


def _tags(given: str, *, sends_to: AdDestination) -> str:
    """The tracking query this advert should carry, once the goal has had a say."""
    if not needs_link(sends_to) or not tags_are_usable(given):
        return ""
    return clean_tags(given)


def _cost_cap(
    *, answers: OnboardingAnswers, goal_of: str
) -> tuple[MinorUnits | None, list[Adjustment]]:
    """The most-per-result figure, once the goal has had a say."""
    given = answers.max_result_cost_minor
    if given is None or given <= 0:
        return None, []
    if not accepts_cap(goal_of):
        return None, [
            Adjustment(
                field="bid_amount", reason="goal_takes_no_cap", detail=str(given)
            )
        ]
    return MinorUnits(int(given)), []


def _quality_promotion(promoted: dict[str, Any], *, upgraded: str) -> dict[str, Any]:
    """What a quality-lead ad set has to say it is optimising towards."""
    if upgraded != QUALITY_GOAL:
        return promoted
    return dict(promoted) | {"custom_event_type": "LEAD"}


DETAILED_KEYS: dict[str, str] = {
    "interest": "interests",
    "behaviour": "behaviors",
    "life_event": "life_events",
}


def _detailed(confirmed: tuple[Interest, ...]) -> dict[str, list[dict[str, str]]]:
    """One flexible-spec block, with each kind under its own key."""
    block: dict[str, list[dict[str, str]]] = {}
    for item in confirmed:
        key = DETAILED_KEYS.get(item.kind)
        if key is None:
            continue
        block.setdefault(key, []).append(_interest(item))
    return block


def _interest(interest: Interest) -> dict[str, str]:
    """Both halves travel. The name is what a person can check later."""
    return {"id": interest.external_id, "name": interest.query}


def _unconfirmed(interests: tuple[Interest, ...]) -> tuple[Adjustment, ...]:
    """Names the provider never confirmed, reported one by one."""
    return tuple(
        Adjustment(
            field="flexible_spec",
            reason="unconfirmed_interest",
            detail=interest.label,
        )
        for interest in interests
        if not interest.is_confirmed
    )


SPECIAL_AD_CATEGORIES: Final[dict[str, str]] = {
    "housing": "HOUSING",
    "employment": "EMPLOYMENT",
    "credit": "FINANCIAL_PRODUCTS_SERVICES",
}


def _categories(business: BusinessProfile) -> tuple[str, ...]:
    """A tuple of at most one. The provider's field is a list, and the
    business profile holds a single value - housing, employment or credit -
    because no business is two of them at once."""
    category = business.special_ad_category.strip().lower()
    if not category:
        return ()
    if category not in SPECIAL_AD_CATEGORIES:
        raise InvalidTargeting(
            f"unknown special ad category {category!r}",
            field="special_ad_category",
        )
    return (SPECIAL_AD_CATEGORIES[category],)


def _category_countries(
    *, business: BusinessProfile, targeting: Mapping[str, Any], geo: GeoChoice | None
) -> tuple[str, ...]:
    """The countries a regulated campaign runs in."""
    if not business.special_ad_category.strip():
        return ()
    named = (targeting.get("geo_locations") or {}).get("countries") or [
        (geo.country_code if geo else "") or business.country_code
    ]
    return tuple(sorted({str(code).upper() for code in named if code}))
