import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.accounts.constants import Language


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    phone: str
    language: str
    is_staff: bool
    date_joined: datetime
    email_verified_at: datetime | None
    welcomed_at: datetime | None
    crm_owner_id: uuid.UUID | None = Field(
        default=None,
        description="Set on a CRM manager's login: whose board it works in.",
    )


class AccountIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    # Absent keeps the number on the row: an account made by staff has none,
    # and renaming it must not demand one.
    phone: str | None = Field(default=None, min_length=1, max_length=32)


class PhoneIn(BaseModel):
    phone: str = Field(min_length=1, max_length=32)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class EmailCodeIn(BaseModel):
    code: str = Field(min_length=5, max_length=5, pattern=r"^\d{5}$")


class LanguageIn(BaseModel):
    language: Language
