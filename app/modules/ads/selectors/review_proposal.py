"""The review screen's proposal: every section, as the owner may edit it."""

from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.money import format_minor, provider_money
from app.common.presets import goal_label
from app.modules.ads import audiences as audience_field
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    INSTAGRAM_ONLY_LABEL,
    INSTAGRAM_ONLY_NOTE,
    LAUNCH_NAME_MAX,
    LEAD_BUYING_NOTES,
    MAX_CUSTOM_QUESTIONS,
    MAX_GEO_PLACES,
    MAX_OPTIONS,
    OFFERED_PLACEMENT_MODES,
    OPTIONS_PENDING,
    PLACEMENT_MODE_NOTES,
    QUESTION_TYPES,
    TARGETING_MODE_NOTES,
    ChatChannel,
    DraftSection,
    LeadBuying,
    PlacementMode,
    TargetingMode,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors import advice
from app.modules.ads.selectors.audiences_chosen import area_options
from app.modules.ads.selectors.campaign_type import (
    campaign_type_card,
    campaign_type_choices,
)
from app.modules.ads.selectors.cards import variant_card
from app.modules.ads.selectors.conversion_event import (
    conversion_event_card,
    conversion_event_choices,
)
from app.modules.ads.selectors.copy_notes import (
    NO_BUTTON,
    copy_notes,
    destination_phone,
)
from app.modules.ads.selectors.delivery_options import cost_cap_choice, delivery_choices
from app.modules.ads.selectors.goals import (
    chosen_channel,
    destination_link,
    goal_optimization,
    goal_preset,
)
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.lead_form import (
    effective_ending,
    ending_fields,
    form_depth_choice,
    privacy_url,
)
from app.modules.ads.selectors.pixel import pixel_choices
from app.modules.ads.selectors.quality import QualityOffer, quality_offer
from app.modules.ads.selectors.schedule import (
    effective_ad_name,
    effective_campaign_name,
    start_day,
)
from app.modules.ads.selectors.tracking import button_choices, url_tags_choice
from app.modules.ads.selectors.variants import (
    launch_variants,
    post_caption,
    post_route,
    promotes_post,
)
from app.modules.ads.summaries import (
    audience_summary,
    form_summary,
    interests_summary,
    traits_summary,
)
from app.modules.businesses.models import Business
from app.modules.integrations.selectors.audiences import targets_for
from app.modules.leads.selectors.reads import FormChoices, usable_forms
from core.targeting.modes import (
    AUTOMATIC_AGE_MAX,
    AUTOMATIC_MAX_AGE_MIN,
    DEFAULT_TARGETING_MODE,
)
from core.targeting.validators import MIN_RADIUS_KM, SPECIAL_MIN_RADIUS_KM


def offered_interests(
    *, proposed: list[dict[str, Any]], chosen: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every interest a box may be drawn for: proposed, then typed."""
    seen = {str(item.get("query", "")) for item in proposed}
    return list(proposed) + [
        item for item in chosen if str(item.get("query", "")) not in seen
    ]


def merged_questions(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """The proposal's questions as chosen, then the ones only chosen."""
    proposed = draft_field.proposal(draft, DraftSection.FORM) or []
    chosen = draft_field.chosen(draft, DraftSection.FORM) or []
    by_kind = {item.get("kind"): item for item in chosen}
    kinds = {item.get("kind") for item in proposed}
    return [by_kind.get(item.get("kind"), item) for item in proposed] + [
        item for item in chosen if item.get("kind") not in kinds
    ]


def proposal_view(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business | None,
    now: datetime,
    greeting: str = "",
) -> dict[str, Any]:
    """Every editable section, for a launch whose proposal is drawn.

    ``greeting`` is the chat's opening words, which only the targeting
    service can work out; the caller passes it in.
    """
    draft = launch.draft or {}
    preset = goal_preset(db, launch=launch)
    special = business.special_ad_category if business is not None else ""
    places = provider_money(provider=launch.provider).decimal_places(launch.currency)
    return {
        "goal": str(launch.answers.get("goal", "")),
        "goal_label": goal_label(preset=preset) if preset is not None else "",
        "budget_label": format_minor(
            amount_minor=launch.daily_budget_minor,
            currency=launch.currency,
            places=places,
        ),
        "start_day": start_day(
            launch=launch,
            zone_name=business.timezone if business is not None else "",
            now=now,
        ),
        "campaign_title": effective_campaign_name(launch=launch, business=business),
        "campaign_named": bool(launch.campaign_name),
        "name_max": LAUNCH_NAME_MAX,
        "audience": _audience(db, launch=launch, special=special, preset=preset),
        "interests": _interests(draft),
        "traits": _traits(draft),
        "variants": _cards(
            db, launch=launch, business=business, preset=preset, now=now
        ),
        "destination": _destination(
            db, launch=launch, business=business, preset=preset, greeting=greeting
        ),
        "lead_form": _lead_form(
            db, launch=launch, business=business, preset=preset, now=now
        ),
        "advanced": _advanced(db, launch=launch),
        "adjustments": [
            note
            for note in draft_field.adjustments(draft)
            if note.get("reason") != "unconfirmed_interest"
        ],
        "unconfirmed_names": [
            str(note.get("detail", ""))
            for note in draft_field.adjustments(draft)
            if note.get("reason") == "unconfirmed_interest"
        ],
        "regenerated": {
            name: draft_field.was_regenerated(draft, name)
            for name in DraftSection.values
        },
        "advice": {
            "audience": advice.audience_recommendation() if not special else None,
            "placement": advice.placement_recommendation(),
        },
    }


def _audience(
    db: Session, *, launch: CampaignLaunch, special: str, preset: Any
) -> dict[str, Any]:
    draft = launch.draft or {}
    audience = draft_field.chosen(draft, DraftSection.AUDIENCE) or {}
    chosen_interests = draft_field.chosen(draft, DraftSection.INTERESTS) or []
    mode = audience.get("targeting_mode") or DEFAULT_TARGETING_MODE
    placement = audience.get("placement_mode") or PlacementMode.AUTOMATIC
    geo = geo_field.stored(audience)
    known = geo_field.known_places(audience)
    quality = (
        quality_offer(
            db, launch=launch, optimization_goal=goal_optimization(db, launch=launch)
        )
        if preset is not None
        else QualityOffer(is_offered=False, is_reporting=False, qualified=0)
    )
    card = audience_summary(
        audience=audience, geo=geo, places=known, mode=mode, placement=placement
    )
    if preset is not None and preset.opens_profile:
        card = replace(card, placement=str(INSTAGRAM_ONLY_LABEL))
    return {
        "chosen": audience,
        "card": card,
        "mode": mode,
        "mode_source": draft_field.source(draft, draft_field.AUDIENCE_MODE),
        "exact_age_mode": TargetingMode.INTERESTS
        if chosen_interests
        else TargetingMode.BROAD,
        "automatic_max_age_min": AUTOMATIC_MAX_AGE_MIN,
        "automatic_age_max": AUTOMATIC_AGE_MAX,
        "modes": []
        if special
        else [
            {
                "value": str(value),
                "label": str(label),
                "note": str(TARGETING_MODE_NOTES[value]),
            }
            for value, label in TargetingMode.choices
        ],
        "placement_mode": placement,
        "placement_source": draft_field.source(draft, draft_field.PLACEMENT_MODE),
        "placement_modes": [
            {
                "value": str(value),
                "label": value.label,
                "note": str(PLACEMENT_MODE_NOTES[value]),
            }
            for value in PlacementMode
            if value in OFFERED_PLACEMENT_MODES or value == placement
        ],
        "placement_pinned": {"label": INSTAGRAM_ONLY_LABEL, "note": INSTAGRAM_ONLY_NOTE}
        if preset is not None and preset.opens_profile
        else None,
        "lead_buying": LeadBuying.QUALITY
        if launch.buy_qualified_leads and quality.is_offered
        else LeadBuying.VOLUME,
        "lead_buying_modes": [
            {"value": value, "label": label, "note": LEAD_BUYING_NOTES[value]}
            for value, label in LeadBuying.choices
        ]
        if quality.is_offered
        else [],
        "quality_offer": quality,
        "buying_advice": advice.buying_recommendation(is_offered=quality.is_offered),
        "geo": geo,
        "geo_places": known,
        "geo_pending": geo_field.waiting_names(audience),
        "geo_unmatched": geo_field.missing_names(audience),
        "geo_areas": area_options(db, country_code=launch_country(db, launch=launch)),
        "geo_chosen_areas": [row["area"] for row in geo_field.areas(audience)],
        "geo_limit": MAX_GEO_PLACES,
        "geo_radius_min": SPECIAL_MIN_RADIUS_KM if special else MIN_RADIUS_KM,
        "targets": _targets(db, launch=launch, special=special),
    }


def launch_country(db: Session, *, launch: CampaignLaunch) -> str:
    from app.modules.businesses.selectors import business_for_page

    business = business_for_page(db, owner=launch.owner, page=launch.page)
    return business.country_code if business is not None else ""


def _targets(
    db: Session, *, launch: CampaignLaunch, special: str
) -> list[dict[str, Any]]:
    """One row per saved audience: its name, its role here, and why not."""
    chosen = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    picked = audience_field.roles(chosen)
    options = targets_for(
        db, owner=launch.owner, account=launch.ad_account, special_ad_category=special
    )
    return [
        {
            "key": option.key,
            "field": audience_field.field_name(option.key),
            "label": option.label,
            "reason": option.blocked_reason,
            "role": picked.get(option.key, ""),
            "disabled": bool(option.blocked_reason) and option.key not in picked,
        }
        for option in options
    ]


def _interests(draft: dict[str, Any]) -> dict[str, Any]:
    proposed = draft_field.proposal(draft, DraftSection.INTERESTS) or []
    chosen = draft_field.chosen(draft, DraftSection.INTERESTS) or []
    stand_in = [
        item
        for item in chosen
        if isinstance(item, dict) and item.get(draft_field.STAND_IN)
    ]
    return {
        "offered": offered_interests(proposed=proposed, chosen=chosen),
        "chosen_queries": [item.get("query", "") for item in chosen],
        "extra": [
            item
            for item in chosen
            if item.get("query") not in {p.get("query") for p in proposed}
        ],
        "confirmed_queries": [
            item.get("query", "") for item in chosen if item.get("external_id")
        ],
        "dropped": draft_field.unconfirmed(draft, DraftSection.INTERESTS),
        "stand_in": stand_in,
        "card": interests_summary(chosen=chosen),
    }


def _traits(draft: dict[str, Any]) -> dict[str, Any]:
    proposed = draft_field.proposal(draft, DraftSection.TRAITS) or []
    chosen = [
        str(item.get("query", ""))
        for item in draft_field.chosen(draft, DraftSection.TRAITS) or []
    ]
    return {
        "offered": proposed,
        "chosen_queries": chosen,
        "dropped": draft_field.unconfirmed(draft, DraftSection.TRAITS),
        "card": traits_summary(proposed=proposed, chosen=chosen),
    }


def _cards(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business | None,
    preset: Any,
    now: datetime,
) -> list[dict[str, Any]]:
    """One card per advert, each with what the word check found in it."""
    sends_to = preset.sends_to if preset is not None else NO_BUTTON
    notes = (
        copy_notes(db, launch=launch, business=business, sends_to=sends_to)
        if business is not None
        else {}
    )
    cards = []
    for variant in launch_variants(db, launch=launch):
        route = (
            post_route(variant=variant, built=preset) if preset is not None else None
        )
        cards.append(
            {
                **variant_card(variant, now=now),
                "copy_notes": notes.get(variant.position, ()),
                "ad_name": effective_ad_name(
                    launch=launch, business=business, variant=variant
                ),
                "ad_named": bool(variant.ad_name),
                "post_route": route.value if route is not None else "",
                "post_route_note": route.label if route is not None else "",
            }
        )
    return cards


def _destination(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business | None,
    preset: Any,
    greeting: str,
) -> dict[str, Any]:
    from app.modules.ads.selectors.launch_page import launch_page as page_of

    opens_chat = preset is not None and preset.opens_chat
    page = page_of(db, launch=launch)
    profile = (
        f"@{page.instagram_username}"
        if preset is not None
        and preset.opens_profile
        and page is not None
        and page.can_open_profile
        else ""
    )
    variants = launch_variants(db, launch=launch)
    return {
        "button_action": preset.sends_to if preset is not None else "",
        "shows_a_button": preset is None or preset.shows_a_button,
        "link": destination_link(launch=launch, business=business)
        if preset is not None and preset.needs_link and business is not None
        else "",
        "opens_chat": opens_chat,
        "chat_channel_label": ChatChannel(chosen_channel(launch=launch)).label
        if opens_chat
        else "",
        "welcome_text": greeting if opens_chat else "",
        "chat_questions": list(launch.answers.get("chat_questions") or []),
        "phone": destination_phone(launch=launch, business=business)
        if preset is not None and preset.needs_phone and business is not None
        else "",
        "profile": profile,
        "promotes_post": bool(
            preset is not None
            and any(
                promotes_post(variant=variant, built=preset) for variant in variants
            )
        ),
        "post_caption": post_caption(db, launch=launch),
    }


def _lead_form(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business | None,
    preset: Any,
    now: datetime,
) -> dict[str, Any] | None:
    if preset is None or not preset.needs_lead_form:
        return None
    draft = launch.draft or {}
    page = launch_page(db, launch=launch)
    forms = (
        usable_forms(db, owner=launch.owner, page=page)
        if page is not None
        else FormChoices(options=(), hidden=0)
    )
    chosen = draft_field.chosen(draft, DraftSection.FORM) or []
    questions = merged_questions(draft)
    kinds = [item.get("kind", "") for item in chosen]
    ending = (
        effective_ending(launch=launch, business=business)
        if business is not None
        else None
    )
    return {
        "questions": questions,
        "chosen_kinds": kinds,
        "custom_kinds": [
            str(item.get("kind", ""))
            for item in questions
            if str(item.get("kind", "")) not in QUESTION_TYPES
        ],
        "standard_kinds": list(QUESTION_TYPES),
        "max_options": MAX_OPTIONS,
        "max_custom": MAX_CUSTOM_QUESTIONS,
        "options_pending": any(
            item.get(OPTIONS_PENDING) for item in chosen if isinstance(item, dict)
        ),
        "lead_forms": forms.options,
        "lead_forms_hidden": forms.hidden,
        "chosen_form": launch.lead_form_external_id,
        "forms_synced_at": page.forms_synced_at if page is not None else None,
        "source": draft_field.source(draft, draft_field.LEAD_FORM),
        "card": form_summary(
            options=forms.options,
            chosen_form=launch.lead_form_external_id,
            questions=questions,
            chosen_kinds=kinds,
        ),
        "advice": advice.form_recommendation(launch=launch, options=forms.options),
        "ending_choice": ending,
        "ending": ending_fields(ending=ending.ending, business=business)
        if ending is not None and business is not None
        else None,
        "depth": form_depth_choice(db, launch=launch, now=now),
        "privacy_url": privacy_url(business) if business is not None else "",
    }


def _advanced(db: Session, *, launch: CampaignLaunch) -> dict[str, Any]:
    return {
        "campaign_card": campaign_type_card(launch=launch),
        "campaign_types": campaign_type_choices(launch=launch),
        "event_card": conversion_event_card(db, launch=launch),
        "conversion_events": conversion_event_choices(db, launch=launch),
        "pixels": pixel_choices(db, launch=launch),
        "buttons": button_choices(db, launch=launch),
        "tracking": url_tags_choice(db, launch=launch),
        "cost_cap": cost_cap_choice(db, launch=launch),
        "delivery": delivery_choices(db, launch=launch),
    }


__all__ = ["merged_questions", "offered_interests", "proposal_view"]
