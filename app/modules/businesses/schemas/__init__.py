import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.common.catalogs import COUNTRY_CODES, timezone_choices
from app.common.phone import is_e164
from app.modules.businesses.constants import MAX_REGIONS

CUSTOM = "__custom__"
Gender = Literal["all", "female", "male"]


class Region(BaseModel):
    """A place the business works in, as the provider's search offered it."""

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["city", "region", "country"]
    country_code: str = Field("", max_length=2)


class BusinessPlaceOut(BaseModel):
    """One row of the place search, as the launch editor's own reads it."""

    id: str
    name: str
    type: Literal["city", "region", "country"]
    context: str = ""
    country_code: str = ""


class ChoiceOut(BaseModel):
    value: str
    label: str


class ProfileChoices(BaseModel):
    categories: list[ChoiceOut]
    countries: list[ChoiceOut]
    timezones: list[ChoiceOut]
    custom_value: str = CUSTOM


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    page_id: uuid.UUID | None
    ad_account_id: uuid.UUID | None
    name: str
    category: str
    category_label: str = ""
    direction_key: str = ""
    custom_label: str = ""
    timezone: str
    country_code: str
    city: str
    lat: Decimal | None
    lng: Decimal | None
    contact_phone: str
    website: str
    offer_text: str
    working_hours: dict[str, Any]
    audience_gender: Gender = "all"
    regions: list[Region] = Field(default_factory=list)


class ProfileForm(BaseModel):
    business: BusinessOut | None
    initial_name: str = ""
    initial_country_code: str = ""
    initial_timezone: str = ""


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=64)
    custom_label: str = Field(default="", max_length=64)
    country_code: str = Field(min_length=2, max_length=2)
    timezone: str = Field(min_length=1, max_length=64)
    city: str | None = Field(default=None, max_length=128)
    contact_phone: str | None = Field(default=None, max_length=20)
    website: HttpUrl | None = None
    offer_text: str | None = None
    working_hours: dict[str, list[str]] | None = None
    audience_gender: Gender | None = Field(
        None, description="Who a new advert is shown to; left out, kept."
    )
    regions: list[Region] | None = Field(
        None,
        max_length=MAX_REGIONS,
        description="Where a new advert is shown, picked from `/business/locations`; left out, kept.",
    )

    @field_validator("country_code")
    @classmethod
    def _country(cls, value: str) -> str:
        if value.upper() not in COUNTRY_CODES:
            raise ValueError("Bunday mamlakat ro'yxatda yo'q.")
        return value.upper()

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        if value not in {zone for zone, _ in timezone_choices()}:
            raise ValueError("Bunday vaqt zonasi yo'q.")
        return value

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if value and not is_e164(value):
            raise ValueError(
                "Telefon raqami xalqaro shaklda bo'lishi kerak: + belgisi va "
                "mamlakat kodi bilan."
            )
        return value
