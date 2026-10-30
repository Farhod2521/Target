from sqlalchemy.orm import Session

from app.common.hooks import fire
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

PHONE_SAVED = "accounts.phone_saved"


def save_account(
    db: Session, *, user: User, full_name: str, phone: str | None = None
) -> User:
    """``phone=None`` keeps the number already on the row."""
    user.full_name = full_name.strip()
    if phone is not None:
        user.phone = phone
    _saved(db, user)
    return user


def save_phone(db: Session, *, user: User, phone: str) -> User:
    user.phone = phone
    _saved(db, user)
    return user


def _saved(db: Session, user: User) -> None:
    fire(PHONE_SAVED, db=db, user=user)
    emit(
        db,
        owner_id=user.id,
        name=EventName.USER_PROFILE_UPDATED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"full_name": user.full_name, "phone": user.phone},
    )
    db.commit()
