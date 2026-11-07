import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.accounts.constants import Language, Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    phone: str
    language: str
    expert_mode: bool = Field(
        default=False,
        description="Reklama and the dashboard open in Expert mode.",
    )
    is_staff: bool
    date_joined: datetime
    email_verified_at: datetime | None
    welcomed_at: datetime | None
    crm_owner_id: uuid.UUID | None = Field(
        default=None,
        description="Set on a CRM manager's login: whose board it works in.",
    )
    role: str = Field(
        default="",
        description="Who the owner said they are (`business_owner`, `targetolog`, "
        "`marketer`, `agency`, `other`); empty until asked.",
    )
    role_needed: bool = Field(
        default=False,
        description="Ask «Siz kimsiz?» once, before anything else: an owner "
        "with no role yet. Never true for a CRM manager.",
    )
    has_password: bool = Field(
        default=True,
        description="False for an account opened by Google: «Parol o'rnatish» "
        "needs no current password.",
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


class ExpertModeIn(BaseModel):
    on: bool


class LanguageIn(BaseModel):
    language: Language


class RoleIn(BaseModel):
    role: Role


class SocialLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    email: str = Field(description="The provider's address at the last sign-in.")
    created_at: datetime
    last_used_at: datetime | None


class SocialLinksOut(BaseModel):
    """Settings' «Kirish usullari»: the providers on offer, the ones tied."""

    providers: list[str]
    linked: list[SocialLinkOut]
    has_password: bool
