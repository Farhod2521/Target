from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.accounts.phone import normalize_email


def user_by_email(db: Session, *, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))
