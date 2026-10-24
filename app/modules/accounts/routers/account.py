from fastapi import APIRouter

from app.api.deps import CurrentUser, Db
from app.modules.accounts import services
from app.modules.accounts.models import User
from app.modules.accounts.phone import clean_phone
from app.modules.accounts.schemas import (
    AccountIn,
    LanguageIn,
    PasswordIn,
    PhoneIn,
    UserOut,
)

router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.put("", response_model=UserOut)
def update(body: AccountIn, user: CurrentUser, db: Db) -> User:
    return services.save_account(
        db, user=user, full_name=body.full_name, phone=clean_phone(body.phone)
    )


@router.put("/phone", response_model=UserOut)
def update_phone(body: PhoneIn, user: CurrentUser, db: Db) -> User:
    return services.save_phone(db, user=user, phone=clean_phone(body.phone))


@router.put("/password", response_model=UserOut)
def update_password(body: PasswordIn, user: CurrentUser, db: Db) -> User:
    return services.change_password(
        db,
        user=user,
        current_password=body.current_password,
        new_password=body.new_password,
    )


@router.put("/language", response_model=UserOut)
def update_language(body: LanguageIn, user: CurrentUser, db: Db) -> User:
    return services.set_language(db, user=user, language=body.language)
