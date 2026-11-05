from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.accounts.phone import normalize_email


def user_by_email(db: Session, *, email: str) -> User | None:
    """Accounts opened before addresses were kept in small letters may hold
    capitals (Django lowered only the domain), so those are found too; an
    exact small-letter row wins over a capitalised twin."""
    address = normalize_email(email)
    return db.scalar(select(User).where(User.email == address)) or db.scalar(
        select(User).where(func.lower(User.email) == address).order_by(User.id).limit(1)
    )
