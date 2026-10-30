from pydantic import BaseModel, EmailStr, Field

from app.modules.accounts.constants import Language
from app.modules.accounts.schemas.account import UserOut


class SignupIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    phone: str = Field(min_length=1, max_length=32)
    language: Language = Language.UZ
    referral_code: str = Field(default="", max_length=32)


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
