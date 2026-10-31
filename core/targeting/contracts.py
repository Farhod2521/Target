"""What the owner told us, before and after it becomes a targeting spec."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from adskit import MinorUnits, TraitKind

from core.targeting.adjustments import Adjustment
from core.targeting.audiences import AudienceChoice
from core.targeting.destinations import (
    DEFAULT_CHAT_CHANNEL,
    AdDestination,
    ChatChannel,
    needs_lead_form,
    needs_link,
    needs_phone,
    opens_chat,
    opens_profile,
    shows_a_button,
)
from core.targeting.modes import DEFAULT_TARGETING_MODE, TargetingMode
from core.targeting.placements import DEFAULT_PLACEMENT_MODE, PlacementMode


@dataclass(frozen=True, slots=True)
class Interest:
    """One targetable interest, in both vocabularies at once."""

    label: str
    query: str
    kind: TraitKind = "interest"
    external_id: str = ""
    audience_size: int = 0

    @property
    def is_confirmed(self) -> bool:
        """Whether the provider agreed this interest exists."""
        return bool(self.external_id)


@dataclass(frozen=True, slots=True)
class ConversionSource:
    """Where a sale on the advertiser's own site is reported from."""

    external_id: str
    name: str = ""

    @property
    def is_usable(self) -> bool:
        return bool(self.external_id)


@dataclass(frozen=True, slots=True)
class QualityLeads:
    """Whether this campaign buys qualified leads instead of submissions."""

    dataset_id: str = ""
    qualified_recently: int = 0
    chosen: bool = False

    @property
    def is_reporting(self) -> bool:
        """Whether verdicts have somewhere to be sent at all."""
        return bool(self.dataset_id)


@dataclass(frozen=True, slots=True)
class BusinessProfile:
    """The advertiser, reduced to what targeting actually needs."""

    name: str
    category: str
    lat: str = ""
    lng: str = ""
    city: str = ""
    country_code: str = ""
    locales: tuple[int, ...] = ()
    special_ad_category: str = ""
    timezone: str = ""
    phone: str = ""


@dataclass(frozen=True, slots=True)
class OnboardingAnswers:
    """The answers a preset is chosen and adapted from."""

    category: str
    goal: str
    daily_budget_minor: MinorUnits
    max_result_cost_minor: MinorUnits | None = None
    total_cap_minor: MinorUnits | None = None
    geo: tuple[str, ...] = ()
    radius_km: int | None = None
    age_min: int | None = None
    age_max: int | None = None
    genders: tuple[int, ...] = ()
    interests: tuple[Interest, ...] = ()
    targeting_mode: TargetingMode = DEFAULT_TARGETING_MODE
    placement_mode: PlacementMode = DEFAULT_PLACEMENT_MODE
    placement_positions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    chat_channel: ChatChannel = DEFAULT_CHAT_CHANNEL
    campaign_type: str = ""
    conversion_event: str = ""
    url_tags: str = ""
    call_to_action: str = ""
    attribution_key: str = ""
    frequency_cap: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class BuiltTargeting:
    """A preset, filled in and checked. The only thing the saga sends."""

    objective: str
    optimization_goal: str
    billing_event: str
    destination_type: str
    targeting: Mapping[str, Any]
    daily_budget_minor: MinorUnits
    sends_to: AdDestination
    call_to_action: str
    currency: str
    special_ad_categories: tuple[str, ...]
    preset_key: str
    preset_version: str
    max_result_cost_minor: MinorUnits | None = None
    total_cap_minor: MinorUnits | None = None
    attribution_days: tuple[int, int] | None = None
    frequency_cap: tuple[int, int] | None = None
    targeting_mode: TargetingMode = DEFAULT_TARGETING_MODE
    placement_mode: PlacementMode = DEFAULT_PLACEMENT_MODE
    promoted_object: Mapping[str, Any] = field(default_factory=dict)
    needs_conversion_source: bool = False
    buys_qualified_leads: bool = False
    audiences: AudienceChoice = field(default_factory=AudienceChoice)
    link_url: str = ""
    welcome_text: str = ""
    autofill_text: str = ""
    welcome_questions: tuple[str, ...] = ()
    phone_number: str = ""
    campaign_type: str = ""
    url_tags: str = ""
    special_ad_category_countries: tuple[str, ...] = ()
    adjustments: tuple[Adjustment, ...] = ()

    @property
    def needs_lead_form(self) -> bool:
        """Whether the sequence has to create a form and hang it on the ad."""
        return needs_lead_form(self.sends_to)

    @property
    def needs_link(self) -> bool:
        """Whether the advertiser's own address is the thing being bought."""
        return needs_link(self.sends_to)

    @property
    def needs_phone(self) -> bool:
        """Whether the button dials instead of opening anything."""
        return needs_phone(self.sends_to)

    @property
    def shows_a_button(self) -> bool:
        """Whether this ad has anywhere at all to send somebody."""
        return shows_a_button(self.sends_to)

    @property
    def opens_chat(self) -> bool:
        """Whether the button opens a conversation instead of a link."""
        return opens_chat(self.sends_to)

    @property
    def opens_profile(self) -> bool:
        """Whether the button opens the business's Instagram profile."""
        return opens_profile(self.sends_to)
