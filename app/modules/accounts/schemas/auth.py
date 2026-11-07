from pydantic import BaseModel, EmailStr, Field

from app.modules.accounts.constants import Language, Role
from app.modules.accounts.schemas.account import UserOut


class SignupIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    phone: str = Field(min_length=1, max_length=32)
    language: Language = Language.UZ
    referral_code: str = Field(default="", max_length=32)
    role: Role | None = Field(
        default=None,
        description="«Siz kimsiz?». The form sends it; an account opened "
        "without it is asked once after signing in (`role_needed`).",
    )


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class CodeSentOut(BaseModel):
    email: str
    expires_in: int
    resend_in: int
    message: str = ""


class PasswordChanged(TokenPair):
    """Every other session ended with the old password; this pair is the
    device that changed it."""

    user: UserOut


class HandoffIn(BaseModel):
    next: str = Field(default="", max_length=512)


class HandoffOut(BaseModel):
    url: str


class HandedOff(TokenPair):
    next: str


class ResetLinkOut(BaseModel):
    """Where "Parolni unutdingizmi?" opens the bot; empty with no bot."""

    bot_url: str


class ResetTargetOut(BaseModel):
    """The account a live new-password link replaces the password of."""

    email: str


class NewPasswordIn(BaseModel):
    new_password1: str = Field(min_length=1, max_length=128)
    new_password2: str = Field(min_length=1, max_length=128)


class SocialProvidersOut(BaseModel):
    """The sign-in pages' buttons, in the order to draw them; empty = none."""

    providers: list[str]


class SocialStartIn(BaseModel):
    next: str = Field(default="", max_length=512)
    referral_code: str = Field(default="", max_length=32)
    language: Language | None = None


class SocialStartOut(BaseModel):
    url: str = Field(description="Google's screen: send the browser there.")


class SocialPendingOut(BaseModel):
    """What the provider gave, shown on the finishing page."""

    provider: str
    email: str = Field(description="Empty from Telegram: `email` is asked.")
    full_name: str
    needs_email: bool = Field(
        default=False, description="The form asks for the email (Telegram)."
    )
    phone: str = Field(
        default="",
        description="The number Telegram verified, +E.164: the phone field starts from it.",
    )


class SocialCompleteIn(BaseModel):
    phone: str = Field(min_length=1, max_length=32)
    role: Role
    full_name: str = Field(
        default="",
        max_length=255,
        description="Empty keeps the name the provider gave.",
    )
    email: EmailStr | None = Field(
        default=None,
        description="Required when `needs_email`; ignored otherwise.",
    )
