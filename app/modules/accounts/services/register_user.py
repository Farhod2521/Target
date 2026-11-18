from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.common.hooks import fire
from app.common.passwords import PasswordInvalid, make_password, validate_password
from app.modules.accounts.constants import (
    SIGNUP_UTM_KEYS,
    SIGNUP_UTM_MAX,
    Language,
    SignupVia,
)
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
    role: str = "",
    utm: dict[str, Any] | None = None,
) -> User:
    """The signup form opens the account at once; the email is confirmed later."""
    email = normalize_email(email)
    if db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
        raise EmailTaken
    try:
        validate_password(password, email=email, full_name=full_name)
    except PasswordInvalid as exc:
        raise InputRefused({"password": str(exc)}) from exc
    return register_user(
        db,
        email=email,
        full_name=full_name,
        password=password,
        phone=phone,
        language=language,
        referral_code=referral_code,
        role=role,
        signup_via=SignupVia.EMAIL,
        signup_utm=utm,
    )


def clean_utm(raw: object) -> dict[str, str]:
    """The landing link's utm_* marks the browser kept, cut to what is
    known and short: anybody may send anything here."""
    if not isinstance(raw, dict):
        return {}
    found = {}
    for key in SIGNUP_UTM_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            found[key] = value.strip()[:SIGNUP_UTM_MAX]
    return found


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
    role: str = "",
    signup_via: str = "",
    signup_utm: object = None,
    commit: bool = True,
) -> User:
    """Neither password given leaves none: an account opened by Google signs
    in by Google until its owner sets one."""
    user = User(
        email=normalize_email(email),
        full_name=full_name.strip(),
        phone=phone,
        language=language,
        role=role,
        password=password_hash or (make_password(password) if password else ""),
        date_joined=utcnow(),
        signup_via=str(signup_via) if signup_via in SignupVia.values else "",
        signup_utm=clean_utm(signup_utm),
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
        payload={"email": user.email, "language": user.language, "role": user.role},
    )
    if commit:
        db.commit()
    return user
