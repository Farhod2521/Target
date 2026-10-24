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
    welcomed_at: datetime | None


class AccountIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=32)


class PhoneIn(BaseModel):
    phone: str = Field(min_length=1, max_length=32)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class LanguageIn(BaseModel):
    language: Language
