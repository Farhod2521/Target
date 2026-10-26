"""Turn the answers and the accepted proposal into a provider spec; apply the
rules' recommendations; and keep the interest names somebody chose."""

from dataclasses import replace
from datetime import timedelta
from typing import Any

from adskit import MinorUnits
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.presets import preset_catalog
from app.modules.accounts.models import User
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    ATTRIBUTION,
    CAMPAIGN_TYPE,
    CHAT_QUESTIONS,
    CONVERSION_EVENT,
    FREQUENCY_CAP,
    LEAD_FORM_CHOICE,
    LEAD_FORM_QUESTIONS,
    URL_TAGS,
    DraftSection,
    InterestSource,
)
from app.modules.ads.models import CampaignLaunch, InterestTerm
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.advice import (
    audience_recommendation,
    campaign_type_recommendation,
    conversion_event_recommendation,
    form_recommendation,
    placement_recommendation,
)
from app.modules.ads.selectors.audiences_chosen import chosen_audiences
from app.modules.ads.selectors.campaign_type import chosen_campaign_type
from app.modules.ads.selectors.conversion_event import (
    chosen_conversion_event,
    offered_events,
)
from app.modules.ads.selectors.copy_notes import destination_phone
from app.modules.ads.selectors.goals import destination_link, goal_preset
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.launches import known_terms, last_geo
from app.modules.ads.selectors.pixel import launch_conversion_source
from app.modules.ads.selectors.tracking import (
    chosen_button,
    chosen_url_tags,
    goal_sends_to_a_site,
)
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount, PageAccount
from core.targeting import (
    CHANNELS,
    DEFAULT_CHAT_CHANNEL,
    DEFAULT_PLACEMENT_MODE,
    DEFAULT_TAGS,
    DEFAULT_TARGETING_MODE,
    MODES,
    PLACEMENT_MODES,
    BuiltTargeting,
    BusinessProfile,
    ChatChannel,
    GeoChoice,
    GeoPlace,
    Interest,
    OnboardingAnswers,
    PlacementMode,
    QualityLeads,
    TargetingMode,
    build,
    clean_questions,
    daily_floor,
    fallback,
    suggested_greeting,
)
from core.targeting.quality import QUALITY_WINDOW_DAYS

WELCOME_KEY = "welcome_text"


def rebuild_targeting(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> None:
    """Rebuild ``launch.targeting`` in place. Does not commit."""
    built = build_for(db, launch=launch, business=business)
    launch.targeting = dict(built.targeting)
    launch.preset_key = built.preset_key
    launch.preset_version = built.preset_version
    launch.currency = built.currency
    draft = fresh(launch, "draft")
    draft_field.set_adjustments(
        draft,
        [
            {"field": note.field, "reason": note.reason, "detail": note.detail}
            for note in built.adjustments
        ],
    )


def build_for(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> BuiltTargeting:
    """The whole built spec, not just the part that gets stored."""
    return build(
        provider=launch.provider,
        answers=launch_answers(db, launch=launch, business=business),
        business=business_profile(business),
        catalog=preset_catalog(),
        currency=launch.ad_account.currency,
        geo=geo_choice(db, launch=launch, business=business),
        conversion=launch_conversion_source(db, launch=launch),
        quality=quality_leads(db, launch=launch),
        audiences=chosen_audiences(
            db, launch=launch, special_ad_category=business.special_ad_category
        ),
        link=destination_link(launch=launch, business=business),
        welcome=welcome_greeting(db, launch=launch, business=business),
        questions=welcome_questions(db, launch=launch),
        phone=destination_phone(launch=launch, business=business),
    )


def welcome_greeting(db: Session, *, launch: CampaignLaunch, business: Business) -> str:
    preset = goal_preset(db, launch=launch)
    if preset is None or not preset.opens_chat:
        return ""
    if WELCOME_KEY in launch.answers:
        return str(launch.answers.get(WELCOME_KEY) or "")
    return suggested_greeting(preset=preset, business=business_profile(business))


def welcome_questions(db: Session, *, launch: CampaignLaunch) -> tuple[str, ...]:
    preset = goal_preset(db, launch=launch)
    if preset is None or not preset.opens_chat:
        return ()
    raw = launch.answers.get(CHAT_QUESTIONS) or []
    return clean_questions(raw if isinstance(raw, list) else [])


def minimum_budget(*, ad_account: AdAccount, optimization_goal: str = "") -> int:
    return daily_floor(
        account_minor=ad_account.min_daily_budget_minor,
        optimization_goal=optimization_goal,
    )


def quality_leads(db: Session, *, launch: CampaignLaunch) -> QualityLeads:
    from app.modules.leads.selectors.reads import qualified_since, reporting_dataset

    if not launch.buy_qualified_leads:
        return QualityLeads()
    since = utcnow() - timedelta(days=QUALITY_WINDOW_DAYS)
    return QualityLeads(
        dataset_id=reporting_dataset(
            db, owner=launch.owner, ad_account=launch.ad_account
        ),
        qualified_recently=qualified_since(db, owner=launch.owner, since=since),
        chosen=True,
    )


def geo_choice(db: Session, *, launch: CampaignLaunch, business: Business) -> GeoChoice:
    chosen = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    choice = geo_field.to_choice(chosen, radius_km=_radius(chosen))
    if choice.is_usable:
        return choice
    offered = suggested_geo(
        db,
        owner=launch.owner,
        business=business,
        page=launch.page,
        radius_km=_radius(chosen),
    )
    return (
        offered if offered.is_usable else fallback(country_code=business.country_code)
    )


def suggested_geo(
    db: Session,
    *,
    owner: User,
    business: Business,
    page: PageAccount | None = None,
    radius_km: int | None = None,
) -> GeoChoice:
    """What to open the geography question on, before anybody answers it."""
    previous = last_geo(db, owner=owner, page=page)
    if previous is not None:
        earlier = geo_field.to_choice(previous, radius_km=_radius(previous))
        if earlier.is_usable:
            return replace(
                earlier, origin="derived", radius_km=radius_km or earlier.radius_km
            )
    if business.lat is not None and business.lng is not None:
        return GeoChoice(
            mode="around",
            lat=str(business.lat),
            lng=str(business.lng),
            radius_km=radius_km,
            country_code=business.country_code,
        )
    from_page = page_geo(
        db, owner=owner, business=business, page=page, radius_km=radius_km
    )
    if from_page is not None:
        return from_page
    return fallback(country_code=business.country_code)


def page_geo(
    db: Session,
    *,
    owner: User,
    business: Business,
    page: PageAccount | None = None,
    radius_km: int | None = None,
) -> GeoChoice | None:
    from app.modules.integrations.selectors import active_page

    page = page or active_page(db, owner=owner)
    if page is None:
        return None
    if page.has_pin:
        return GeoChoice(
            mode="around",
            lat=str(page.location_lat),
            lng=str(page.location_lng),
            radius_km=radius_km,
            country_code=business.country_code,
        )
    if page.location_city_key:
        return GeoChoice(
            mode="places",
            places=(
                GeoPlace(
                    key=page.location_city_key, name=page.location_city, kind="city"
                ),
            ),
            country_code=business.country_code,
        )
    return None


def _radius(chosen: Any) -> int | None:
    if not isinstance(chosen, dict):
        return None
    value = chosen.get("radius_km")
    return int(value) if isinstance(value, int | str) and str(value).isdigit() else None


def _geo_names(launch: CampaignLaunch) -> tuple[str, ...]:
    chosen = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    return tuple(
        place.name for place in geo_field.to_choice(chosen).usable_places if place.name
    )


def business_profile(business: Business) -> BusinessProfile:
    return BusinessProfile(
        name=business.name,
        category=business.category,
        lat="" if business.lat is None else str(business.lat),
        lng="" if business.lng is None else str(business.lng),
        city=business.city,
        country_code=business.country_code,
        locales=tuple(business.locales or ()),
        special_ad_category=business.special_ad_category,
        timezone=business.timezone,
        phone=business.contact_phone,
    )


def launch_answers(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> OnboardingAnswers:
    """The wizard's answers and the accepted audience, as one value."""
    audience = draft_field.chosen(launch.draft, "audience") or {}
    return OnboardingAnswers(
        category=business.category,
        goal=str(launch.answers.get("goal", "")),
        daily_budget_minor=MinorUnits(int(launch.daily_budget_minor or 0)),
        max_result_cost_minor=MinorUnits(int(launch.max_result_cost_minor))
        if launch.max_result_cost_minor
        else None,
        geo=_geo_names(launch),
        radius_km=_int_or_none(audience.get("radius_km")),
        age_min=_int_or_none(audience.get("age_min")),
        age_max=_int_or_none(audience.get("age_max")),
        genders=tuple(int(g) for g in audience.get("genders") or ()),
        interests=chosen_interests(db, launch=launch) + chosen_traits(launch=launch),
        targeting_mode=_mode(audience.get("targeting_mode")),
        placement_mode=_placement(audience.get("placement_mode")),
        chat_channel=_channel(launch.answers.get("chat_channel")),
        campaign_type=chosen_campaign_type(launch=launch),
        conversion_event=chosen_conversion_event(launch=launch),
        url_tags=chosen_url_tags(launch=launch),
        call_to_action=chosen_button(launch=launch),
        attribution_key=str(launch.answers.get(ATTRIBUTION) or ""),
        frequency_cap=_frequency(launch.answers.get(FREQUENCY_CAP)),
        total_cap_minor=_minor(launch.total_cap_minor),
    )


def _frequency(value: object) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        times, days = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    return (times, days) if times > 0 and days > 0 else None


def _minor(amount: int | None) -> MinorUnits | None:
    return MinorUnits(int(amount)) if amount else None


def _mode(value: object) -> TargetingMode:
    return value if value in MODES else DEFAULT_TARGETING_MODE  # type: ignore[return-value]


def _placement(value: object) -> PlacementMode:
    return value if value in PLACEMENT_MODES else DEFAULT_PLACEMENT_MODE  # type: ignore[return-value]


def _channel(value: object) -> ChatChannel:
    return value if value in CHANNELS else DEFAULT_CHAT_CHANNEL  # type: ignore[return-value]


def chosen_traits(*, launch: CampaignLaunch) -> tuple[Interest, ...]:
    picked = draft_field.chosen(launch.draft, DraftSection.TRAITS) or []
    return tuple(
        Interest(
            label=str(item.get("label", "")),
            query=str(item.get("query", "")),
            kind=str(item.get("kind", "")) or "interest",
            external_id=str(item.get("external_id") or ""),
        )
        for item in picked
        if isinstance(item, dict) and item.get("query")
    )


def chosen_interests(db: Session, *, launch: CampaignLaunch) -> tuple[Interest, ...]:
    picked = draft_field.chosen(launch.draft, "interests") or []
    rows = known_terms(
        db,
        owner=launch.owner,
        provider=launch.provider,
        queries=[str(item.get("query", "")) for item in picked],
    )
    interests: list[Interest] = []
    for item in picked:
        query = str(item.get("query", ""))
        cached = rows.get(query)
        interests.append(
            Interest(
                label=str(item.get("label", query)),
                query=query,
                external_id=str(item.get("external_id") or "")
                or (cached.external_id if cached else ""),
                audience_size=int(
                    item.get("audience_size")
                    or (cached.audience_size if cached and cached.audience_size else 0)
                ),
            )
        )
    return tuple(interests)


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)  # type: ignore[call-overload]


# -- the rules' recommendations, applied --------------------------------------------


def _draft(launch: CampaignLaunch) -> dict[str, Any]:
    return fresh(launch, "draft")  # type: ignore[no-any-return]


def apply_placement(db: Session, *, launch: CampaignLaunch) -> None:
    draft = _draft(launch)
    if draft_field.source(draft, draft_field.PLACEMENT_MODE):
        return
    advice = placement_recommendation()
    _settle(launch, field="placement_mode", value=advice.value)
    draft_field.set_source(launch.draft, draft_field.PLACEMENT_MODE, draft_field.BY_AI)


def apply_lead_form(db: Session, *, launch: CampaignLaunch) -> None:
    """Which form collects the answers: one that already exists, or a new one."""
    from app.modules.leads.selectors.reads import usable_forms

    draft = _draft(launch)
    if draft_field.source(draft, draft_field.LEAD_FORM):
        return
    preset = goal_preset(db, launch=launch)
    if preset is None or not preset.needs_lead_form:
        return
    if launch.answers.get(LEAD_FORM_CHOICE) == draft_field.BY_OWNER:
        draft_field.set_source(draft, draft_field.LEAD_FORM, draft_field.BY_OWNER)
        questions = launch.answers.get(LEAD_FORM_QUESTIONS)
        if questions:
            draft_field.choose(
                draft, DraftSection.FORM, draft_field.with_phone(list(questions))
            )
        return
    page = launch_page(db, launch=launch)
    if page is None:
        return
    advice = form_recommendation(
        launch=launch, options=usable_forms(db, owner=launch.owner, page=page).options
    )
    if advice is None:
        return
    launch.lead_form_external_id = advice.value
    draft_field.set_source(draft, draft_field.LEAD_FORM, draft_field.BY_AI)


def apply_campaign_type(db: Session, *, launch: CampaignLaunch) -> None:
    draft = _draft(launch)
    if launch.answers.get(CAMPAIGN_TYPE) or draft_field.source(
        draft, draft_field.CAMPAIGN_TYPE
    ):
        return
    advice = campaign_type_recommendation(launch=launch)
    if advice is None:
        return
    draft_field.set_campaign_type(draft, advice.value)
    draft_field.set_source(draft, draft_field.CAMPAIGN_TYPE, draft_field.BY_AI)


def apply_conversion_event(db: Session, *, launch: CampaignLaunch) -> None:
    draft = _draft(launch)
    if launch.answers.get(CONVERSION_EVENT) or draft_field.source(
        draft, draft_field.CONVERSION_EVENT
    ):
        return
    offered = tuple(row.key for row in offered_events(db, launch=launch))
    advice = conversion_event_recommendation(db, launch=launch, offered=offered)
    if advice is None:
        return
    draft_field.set_conversion_event(draft, advice.value)
    draft_field.set_source(draft, draft_field.CONVERSION_EVENT, draft_field.BY_AI)


def apply_url_tags(db: Session, *, launch: CampaignLaunch) -> None:
    draft = _draft(launch)
    if URL_TAGS in launch.answers or draft_field.source(draft, draft_field.URL_TAGS):
        return
    if not goal_sends_to_a_site(db, launch=launch):
        return
    draft_field.set_url_tags(draft, DEFAULT_TAGS)
    draft_field.set_source(draft, draft_field.URL_TAGS, draft_field.BY_AI)


def apply_audience_mode(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> bool:
    """How much of the audience decision to keep. Returns whether to re-ask."""
    draft = _draft(launch)
    if draft_field.source(draft, draft_field.AUDIENCE_MODE):
        return False
    if business.special_ad_category:
        return False
    advice = audience_recommendation()
    changed = _settle(
        launch, field="targeting_mode", value=advice.value, unset=DEFAULT_TARGETING_MODE
    )
    draft_field.set_source(launch.draft, draft_field.AUDIENCE_MODE, draft_field.BY_AI)
    rebuild_targeting(db, launch=launch, business=business)
    db.flush()
    return changed


def _settle(launch: CampaignLaunch, *, field: str, value: str, unset: str = "") -> bool:
    draft = _draft(launch)
    chosen = dict(draft_field.chosen(draft, DraftSection.AUDIENCE) or {})
    moved = chosen.get(field, unset) != value
    chosen[field] = value
    draft_field.choose(draft, DraftSection.AUDIENCE, chosen)
    return moved


# -- the interest cache ---------------------------------------------------------------


def _term(db: Session, launch: CampaignLaunch, query: str) -> InterestTerm | None:
    return db.scalar(
        select(InterestTerm).where(
            InterestTerm.owner_id == launch.owner_id,
            InterestTerm.provider == launch.provider,
            InterestTerm.query == query,
        )
    )


def remember_terms(
    db: Session,
    *,
    launch: CampaignLaunch,
    items: list[dict[str, str]],
    source: InterestSource,
) -> None:
    """Cache the chosen names, without disturbing what is already known."""
    for item in items:
        query = (item.get("query") or "").strip()
        if not query:
            continue
        label = (item.get("label") or query).strip()
        term = _term(db, launch, query)
        if term is None:
            db.add(
                InterestTerm(
                    owner_id=launch.owner_id,
                    provider=launch.provider,
                    query=query,
                    label=label,
                    source=str(source),
                )
            )
            db.flush()
        elif not term.label:
            term.label = label
    db.flush()


def confirm_terms(
    db: Session,
    *,
    launch: CampaignLaunch,
    confirmed: tuple[Interest, ...],
    missing: tuple[Interest, ...],
    source: InterestSource = InterestSource.AI,
) -> None:
    """Write down what the provider answered about each name."""
    now = utcnow()
    for interest in confirmed:
        _write(
            db,
            launch=launch,
            interest=interest,
            source=source,
            external_id=interest.external_id,
            audience_size=interest.audience_size or None,
            confirmed_at=now,
        )
    for interest in missing:
        _write(
            db,
            launch=launch,
            interest=interest,
            source=source,
            external_id="",
            audience_size=None,
            confirmed_at=None,
        )
    db.flush()


def _write(
    db: Session,
    *,
    launch: CampaignLaunch,
    interest: Interest,
    source: InterestSource,
    external_id: str,
    audience_size: int | None,
    confirmed_at: Any,
) -> None:
    query = interest.query.strip()
    if not query:
        return
    term = _term(db, launch, query)
    if term is None:
        term = InterestTerm(
            owner_id=launch.owner_id, provider=launch.provider, query=query
        )
        db.add(term)
    term.label = interest.label.strip() or query
    term.external_id = external_id
    term.audience_size = audience_size
    term.confirmed_at = confirmed_at
    term.source = str(source)
    db.flush()
