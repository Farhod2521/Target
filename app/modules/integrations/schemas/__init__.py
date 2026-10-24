import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Row(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConnectionOut(_Row):
    id: uuid.UUID
    provider: str
    status: str
    external_user_name: str
    scopes: list[str]
    expires_at: datetime | None
    last_verified_at: datetime | None
    action_required_at: datetime | None


class AdAccountOut(_Row):
    id: uuid.UUID
    provider: str
    external_id: str
    name: str
    currency: str
    timezone: str
    account_status: str
    may_advertise: bool | None
    payment_due: bool | None
    is_active: bool
    is_current: bool
    cap_reached: bool
    synced_at: datetime | None


class PageOut(_Row):
    id: uuid.UUID
    provider: str
    external_id: str
    name: str
    is_active: bool
    is_current: bool
    may_advertise: bool | None
    leadgen_subscribed: bool
    leadgen_terms_accepted: bool | None
    has_instagram: bool
    instagram_user_id: str
    instagram_username: str
    location_city: str
    ad_account_id: uuid.UUID | None


class PixelOut(_Row):
    id: uuid.UUID
    external_id: str
    name: str
    is_active: bool
    is_unavailable: bool
    last_fired_at: datetime | None


class SlotsOut(BaseModel):
    allowed: int
    used: int
    free: int
    has_room: bool


class InstagramChoiceOut(_Row):
    instagram_user_id: str
    username: str
    is_page_own: bool
    is_active: bool
    is_linked: bool


class PayerOptionOut(BaseModel):
    account: AdAccountOut
    recommended: bool
    unusable: bool


class PagePayerOut(BaseModel):
    page: PageOut | None
    payer: AdAccountOut | None
    options: list[PayerOptionOut]
    paired: list[AdAccountOut]


class PageRowOut(BaseModel):
    page: PageOut
    profile_id: uuid.UUID | None
    payer: PagePayerOut
    terms_url: str
    bill_url: str
    instagrams: list[InstagramChoiceOut]
    account: AdAccountOut | None


class PairOut(BaseModel):
    key: str
    page: PageOut
    account: AdAccountOut
    stored: bool
    first: bool


class ActionRequiredOut(BaseModel):
    person: str
    manager_url: str
    repeated: bool


class InstagramProfileOut(_Row):
    page_id: str
    user_id: str
    username: str
    name: str
    biography: str
    website: str
    picture_url: str
    followers: int | None
    follows: int | None
    posts: int | None
    synced_at: datetime | None
    can_refresh: bool
    is_read: bool


class ProfileCardOut(BaseModel):
    instagram_profile: InstagramProfileOut | None
    profile_waiting: bool
    profile_late: bool
    profile_since: int
    profile_tries: int
    profile_error: str = ""


class GoogleCardOut(BaseModel):
    google_ads_on: bool
    connection: ConnectionOut | None = None
    connected: bool = False
    accounts: list[AdAccountOut] = []
    subscribed: list[dict[str, Any]] = []
    others: list[AdAccountOut] = []
    slots: SlotsOut | None = None
    loading: bool = False
    taken: list[dict[str, Any]] = []
    has_subscription: bool = False


class ConnectionsOut(BaseModel):
    connection: ConnectionOut | None
    is_connected: bool
    may_connect: bool
    enabled_rows: list[PageRowOut]
    page_slots: SlotsOut
    setup_locked: bool
    ad_accounts: list[AdAccountOut]
    ad_accounts_taken: list[dict[str, Any]]
    spare_pages: list[PageOut]
    active_page: PageOut | None
    active_ad_account: AdAccountOut | None
    any_without_instagram: bool
    ig_needs_permission: bool
    pixels: list[PixelOut]
    active_pixel: PixelOut | None
    instagram: ProfileCardOut
    google: GoogleCardOut
    add_page: dict[str, Any]


class CabinetOut(BaseModel):
    pages: list[PageOut]
    pairs: list[PairOut]
    pair: PairOut | None
    switchable: bool
    room: int
    google_ads_nav: bool
    pair_prompt: PagePayerOut | None
    meta_connection_broken: ConnectionOut | None
    meta_action_required: ActionRequiredOut | None


class OAuthStartOut(BaseModel):
    url: str


class OAuthStartIn(BaseModel):
    next: str = ""


class ExternalIdIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=128)


class PagesIn(BaseModel):
    external_ids: list[str] = Field(min_length=1)
    ad_account: str = ""


class PairIn(BaseModel):
    page: str = Field(min_length=1, max_length=128)
    external_id: str = Field(min_length=1, max_length=128)


class InstagramIn(BaseModel):
    page: str = Field(min_length=1, max_length=128)
    instagram: str = Field(min_length=1, max_length=64)
    action: str = "add"


class MessageOut(BaseModel):
    detail: str


def _squash(value: str) -> str:
    return " ".join(value.split())


class AudienceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)

    _clean = field_validator("name", "description")(_squash)


class RuleAudienceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1)
    action: str = Field(min_length=1)
    retention_days: int = Field(gt=0)

    _clean = field_validator("name")(_squash)


class LookalikeAudienceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    origin: str = Field(min_length=1)
    breadth: str = Field(min_length=1)

    _clean = field_validator("name")(_squash)


class AudienceOut(_Row):
    id: uuid.UUID
    external_id: str
    name: str
    description: str
    subtype_raw: str
    accepts_members: bool
    can_seed: bool
    approximate_count_lower: int
    approximate_count_upper: int
    is_ready: bool
    is_counted: bool
    is_lookalike: bool
    is_rule_built: bool
    readiness_text: str
    processing_text: str
    source_kind: str
    source_action: str
    source_label: str
    origin_label: str
    breadth: str
    retention_days: int
    members_sent: int
    members_invalid: int
    last_filled_at: datetime | None
    synced_at: datetime | None


class OptionOut(BaseModel):
    kind: str = ""
    external_id: str = ""
    label: str
    blocked_reason: str = ""


class RuleOptionOut(BaseModel):
    kind: str
    label: str
    actions: list[tuple[str, str]]
    windows: list[int]


class AudiencesOut(BaseModel):
    audiences: list[AudienceOut]
    ad_account: AdAccountOut | None
    sources: list[OptionOut]
    rule_options: list[RuleOptionOut]
    seeds: list[OptionOut]
    breadths: list[tuple[str, str, str]]
    business_country: str
    action_notes: dict[str, str]
    min_members: int
    useful_members: int
    terms_url: str
    syncing: bool
    tries: int
