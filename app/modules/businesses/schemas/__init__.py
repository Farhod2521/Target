import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.common.catalogs import COUNTRY_CODES, timezone_choices
from app.common.phone import is_e164

CUSTOM = "__custom__"


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
