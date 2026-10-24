"""Targeting construction.

Turns a category and a goal into a Meta targeting spec, using the YAML
presets in ``catalog/``. Presets are data, not code: adding a business
category must not require a deploy of new logic.

An audience is built one of three ways - the interests the advertiser
approved, a broad spec with no detailed targeting at all, or the provider
choosing for itself. Which one is an **answer** and never a reading of the
finished spec; see :mod:`core.targeting.modes`.

Beside all three sits a second question - which of the advertiser's own
audiences to aim at or keep away from. It arrives as an argument rather
than an answer, like the geography and the conversion source, because an
audience is a row somewhere this package cannot read; see
:mod:`core.targeting.audiences`.

Nothing in here reads a clock, a database, an environment variable or a
socket. Everything arrives as an argument and leaves as a value, which is
what lets the whole flow be exercised before any provider is connected -
the wizard has to work for someone who has not linked an account yet.
"""

from core.targeting.adjustments import Adjustment, AdjustmentReason
from core.targeting.attribution import (
    WINDOWS,
    AttributionWindow,
    attribution_window,
    takes_attribution,
    windows_for,
)
from core.targeting.audiences import (
    EXCLUDE_KEY,
    INCLUDE_KEY,
    MAX_PER_SIDE,
    AudienceChoice,
    AudienceRef,
)
from core.targeting.budget import (
    accepts_cap,
    cap_fits,
    daily_floor,
    min_daily_for_cap,
    spend_limits_fit,
)
from core.targeting.builder import build
from core.targeting.buttons import (
    BUTTONS,
    FIXED_BUTTONS,
    AdButton,
    button,
    buttons_for,
)
from core.targeting.calls import dialable, is_local
from core.targeting.campaign_types import (
    CAMPAIGN_TYPES,
    CampaignType,
    ObjectiveGroup,
    campaign_type,
    default_type,
    type_built_as,
    types_for,
)
from core.targeting.chat import (
    MAX_AUTOFILL_CHARS,
    MAX_CHAT_QUESTIONS,
    MAX_GREETING_CHARS,
    MAX_QUESTION_CHARS,
    clean_questions,
    suggested_greeting,
)
from core.targeting.compat import (
    OFFERS,
    OUTCOMES,
    AccountFacts,
    Offer,
    Outcome,
    OutcomeSpec,
    Requirement,
    choices_for,
    closed_by,
    default_offer,
    is_open,
    listed_for,
    nearest_open,
    needs_pixel,
    offer,
    offers_for,
    outcome_default,
    outcome_of,
    outcome_spec,
)
from core.targeting.confirm import (
    STAND_IN_TARGET,
    Confirmation,
    Found,
    apply_found,
    needs_lookup,
    retranslate,
    stand_in_room,
    stand_ins,
)
from core.targeting.contracts import (
    BuiltTargeting,
    BusinessProfile,
    ConversionSource,
    Interest,
    OnboardingAnswers,
    QualityLeads,
)
from core.targeting.conversion_events import (
    CONVERSION_EVENTS,
    EVENT_KEY,
    REQUEST_EVENTS,
    SNIPPET_EVENTS,
    ConversionEvent,
    conversion_event,
    conversion_events,
    counts_a_request,
    event_for_snippet,
    events_for,
)
from core.targeting.describe import AudienceSketch, describe
from core.targeting.destinations import (
    CHANNELS,
    DEFAULT_CHAT_CHANNEL,
    DELIVERABLE,
    DESTINATIONS,
    AdDestination,
    ChatChannel,
)
from core.targeting.exceptions import (
    AudienceUnusable,
    BudgetTooLow,
    CatalogError,
    ConversionSourceMissing,
    CostCapTooLow,
    DestinationLinkMissing,
    InvalidTargeting,
    LookalikeNotAllowed,
    NoInterestsChosen,
    PhoneNumberMissing,
    PhoneNumberUnusable,
    PresetNotFound,
    TargetingError,
    UnfilledTemplate,
)
from core.targeting.gate import validate_launchable
from core.targeting.geo import (
    DISTANCE_UNIT,
    GeoChoice,
    GeoMode,
    GeoOrigin,
    GeoPlace,
    fallback,
    geo_locations,
    pins,
)
from core.targeting.modes import (
    DEFAULT_TARGETING_MODE,
    MODES,
    TargetingMode,
    requires_interests,
    resolve_mode,
    sent_ages,
    wants_interests,
)
from core.targeting.placements import (
    DEFAULT_PLACEMENT_MODE,
    PLACEMENT_MODES,
    RETIRED_POSITIONS,
    STANDARD_PLACEMENTS,
    PlacementMode,
)
from core.targeting.presets import CATALOG_DIR, Category, Preset, PresetCatalog
from core.targeting.quality import (
    BUYING_MODES,
    DEFAULT_BUYING,
    MIN_QUALIFIED_FOR_QUALITY,
    QUALITY_GOAL,
    QUALITY_WINDOW_DAYS,
    LeadBuying,
)
from core.targeting.revise import (
    FEMALE,
    MALE,
    AudienceEdit,
    changed,
    revise,
)
from core.targeting.tracking import (
    DEFAULT_TAGS,
    clean_tags,
    tags_are_usable,
)
from core.targeting.validators import (
    MAX_AGE,
    MAX_RADIUS_KM,
    MIN_AGE,
    MIN_RADIUS_KM,
    validate_structure,
)

__all__ = [
    "BUTTONS",
    "BUYING_MODES",
    "CAMPAIGN_TYPES",
    "CATALOG_DIR",
    "CHANNELS",
    "CONVERSION_EVENTS",
    "DEFAULT_BUYING",
    "DEFAULT_CHAT_CHANNEL",
    "DEFAULT_PLACEMENT_MODE",
    "DEFAULT_TAGS",
    "DEFAULT_TARGETING_MODE",
    "DELIVERABLE",
    "DESTINATIONS",
    "DISTANCE_UNIT",
    "EVENT_KEY",
    "EXCLUDE_KEY",
    "FEMALE",
    "FIXED_BUTTONS",
    "INCLUDE_KEY",
    "MALE",
    "MAX_AGE",
    "MAX_AUTOFILL_CHARS",
    "MAX_CHAT_QUESTIONS",
    "MAX_GREETING_CHARS",
    "MAX_PER_SIDE",
    "MAX_QUESTION_CHARS",
    "MAX_RADIUS_KM",
    "MIN_AGE",
    "MIN_QUALIFIED_FOR_QUALITY",
    "MIN_RADIUS_KM",
    "MODES",
    "OFFERS",
    "OUTCOMES",
    "PLACEMENT_MODES",
    "QUALITY_GOAL",
    "QUALITY_WINDOW_DAYS",
    "REQUEST_EVENTS",
    "RETIRED_POSITIONS",
    "SNIPPET_EVENTS",
    "STANDARD_PLACEMENTS",
    "STAND_IN_TARGET",
    "WINDOWS",
    "AccountFacts",
    "AdButton",
    "AdDestination",
    "Adjustment",
    "AdjustmentReason",
    "AttributionWindow",
    "AudienceChoice",
    "AudienceEdit",
    "AudienceRef",
    "AudienceSketch",
    "AudienceUnusable",
    "BudgetTooLow",
    "BuiltTargeting",
    "BusinessProfile",
    "CampaignType",
    "CatalogError",
    "Category",
    "ChatChannel",
    "Confirmation",
    "ConversionEvent",
    "ConversionSource",
    "ConversionSourceMissing",
    "CostCapTooLow",
    "DestinationLinkMissing",
    "Found",
    "GeoChoice",
    "GeoMode",
    "GeoOrigin",
    "GeoPlace",
    "Interest",
    "InvalidTargeting",
    "LeadBuying",
    "LookalikeNotAllowed",
    "NoInterestsChosen",
    "ObjectiveGroup",
    "Offer",
    "OnboardingAnswers",
    "Outcome",
    "OutcomeSpec",
    "PhoneNumberMissing",
    "PhoneNumberUnusable",
    "PlacementMode",
    "Preset",
    "PresetCatalog",
    "PresetNotFound",
    "QualityLeads",
    "Requirement",
    "TargetingError",
    "TargetingMode",
    "UnfilledTemplate",
    "accepts_cap",
    "apply_found",
    "attribution_window",
    "build",
    "button",
    "buttons_for",
    "campaign_type",
    "cap_fits",
    "changed",
    "choices_for",
    "clean_questions",
    "clean_tags",
    "closed_by",
    "conversion_event",
    "conversion_events",
    "counts_a_request",
    "daily_floor",
    "default_offer",
    "default_type",
    "describe",
    "dialable",
    "event_for_snippet",
    "events_for",
    "fallback",
    "geo_locations",
    "is_local",
    "is_open",
    "listed_for",
    "min_daily_for_cap",
    "nearest_open",
    "needs_lookup",
    "needs_pixel",
    "offer",
    "offers_for",
    "outcome_default",
    "outcome_of",
    "outcome_spec",
    "pins",
    "requires_interests",
    "resolve_mode",
    "retranslate",
    "revise",
    "sent_ages",
    "spend_limits_fit",
    "stand_in_room",
    "stand_ins",
    "suggested_greeting",
    "tags_are_usable",
    "takes_attribution",
    "type_built_as",
    "types_for",
    "validate_launchable",
    "validate_structure",
    "wants_interests",
    "windows_for",
]
