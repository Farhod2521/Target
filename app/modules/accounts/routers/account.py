from dataclasses import asdict

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Db
from app.modules.accounts import services
from app.modules.accounts.constants import SocialProvider
from app.modules.accounts.models import User
from app.modules.accounts.phone import clean_phone
from app.modules.accounts.routers.auth import token_pair
from app.modules.accounts.schemas import (
    AccountIn,
    CodeSentOut,
    EmailCodeIn,
    ExpertModeIn,
    LanguageIn,
    PasswordChanged,
    PasswordIn,
    PhoneIn,
    RoleIn,
    SocialLinkOut,
    SocialLinksOut,
    SocialStartIn,
    SocialStartOut,
    UserOut,
)
from app.modules.accounts.services import social_login

router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.put("", response_model=UserOut)
def update(body: AccountIn, user: CurrentUser, db: Db) -> User:
    phone = None if body.phone is None else clean_phone(body.phone)
    return services.save_account(db, user=user, full_name=body.full_name, phone=phone)


@router.put("/phone", response_model=UserOut)
def update_phone(body: PhoneIn, user: CurrentUser, db: Db) -> User:
    return services.save_phone(db, user=user, phone=clean_phone(body.phone))


@router.put("/password", response_model=PasswordChanged)
def update_password(body: PasswordIn, user: CurrentUser, db: Db) -> PasswordChanged:
    """Every other device is signed out; this one carries on with the new pair."""
    services.change_password(
        db,
        user=user,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    pair = token_pair(user)
    return PasswordChanged(
        user=UserOut.model_validate(user),
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.put("/expert-mode", response_model=UserOut)
def update_expert_mode(body: ExpertModeIn, user: CurrentUser, db: Db) -> User:
    """Open Reklama and the dashboard in Expert mode, or in the plain one."""
    return services.set_expert_mode(db, user=user, on=body.on)


@router.put("/role", response_model=UserOut)
def update_role(body: RoleIn, user: CurrentUser, db: Db) -> User:
    """«Siz kimsiz?» - answered once when ``role_needed``, changeable later."""
    return services.set_role(db, user=user, role=body.role)


@router.get("/social", response_model=SocialLinksOut)
def social_links(user: CurrentUser, db: Db) -> SocialLinksOut:
    return SocialLinksOut(
        providers=social_login.providers(),
        linked=[
            SocialLinkOut.model_validate(identity)
            for identity in social_login.linked(db, owner=user)
        ],
        has_password=user.has_password,
    )


@router.post("/social/{provider}/start", response_model=SocialStartOut)
def social_link_start(
    provider: SocialProvider, body: SocialStartIn, user: CurrentUser
) -> SocialStartOut:
    """Tie a Google account to this one, whatever its email. The browser
    comes back to ``next`` (Settings by default) with ``?linked=google`` or
    ``?social_error=taken|cancelled|failed|expired``."""
    url = social_login.start(provider=provider.value, next_path=body.next, linking=user)
    return SocialStartOut(url=url)


@router.delete("/social/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def social_unlink(provider: SocialProvider, user: CurrentUser, db: Db) -> None:
    """Refused (``social_last_way``) while it is the only way in."""
    social_login.unlink(db, owner=user, provider=provider.value)


@router.put("/language", response_model=UserOut)
def update_language(body: LanguageIn, user: CurrentUser, db: Db) -> User:
    return services.set_language(db, user=user, language=body.language)


@router.post(
    "/email/code", response_model=CodeSentOut, status_code=status.HTTP_202_ACCEPTED
)
def send_email_code(user: CurrentUser) -> CodeSentOut:
    """Mail a five-digit code to confirm the account's email. Optional."""
    sent = services.send_email_code(user=user)
    return CodeSentOut(
        **asdict(sent), message="Emailingizga 5 xonali tasdiqlash kodi yuborildi."
    )


@router.post("/email/verify", response_model=UserOut)
def verify_email(body: EmailCodeIn, user: CurrentUser, db: Db) -> User:
    return services.confirm_email(db, user=user, code=body.code)
