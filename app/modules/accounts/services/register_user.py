from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.exceptions import DomainError
from app.common.hooks import fire
from app.common.passwords import PasswordInvalid, make_password, validate_password
from app.modules.accounts.constants import Language
from app.modules.accounts.exceptions import EmailTaken
from app.modules.accounts.models import User
from app.modules.accounts.phone import normalize_email
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

USER_REGISTERED = "accounts.user_registered"


def sign_up(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    phone: str,
    language: str,
    referral_code: str = "",
) -> User:
    """The signup form opens the account at once; the email is confirmed later."""
    email = normalize_email(email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise EmailTaken
    try:
        validate_password(password, email=email, full_name=full_name)
    except PasswordInvalid as exc:
        raise DomainError(str(exc)) from exc
    return register_user(
        db,
        email=email,
        full_name=full_name,
        password=password,
        phone=phone,
        language=language,
        referral_code=referral_code,
    )


def register_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str = "",
    password_hash: str = "",
    phone: str = "",
    language: str = Language.UZ,
    referral_code: str = "",
) -> User:
    user = User(
        email=normalize_email(email),
        full_name=full_name.strip(),
        phone=phone,
        language=language,
        password=password_hash or make_password(password),
        date_joined=utcnow(),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise EmailTaken from None
    fire(USER_REGISTERED, db=db, user=user, referral_code=referral_code)
    emit(
        db,
        owner_id=user.id,
        name=EventName.USER_REGISTERED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"email": user.email, "language": user.language},
    )
    db.commit()
    return user
