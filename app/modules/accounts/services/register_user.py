from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.hooks import fire
from app.common.passwords import make_password
from app.modules.accounts.constants import Language
from app.modules.accounts.exceptions import EmailTaken
from app.modules.accounts.models import User
from app.modules.accounts.phone import normalize_email
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

USER_REGISTERED = "accounts.user_registered"


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
