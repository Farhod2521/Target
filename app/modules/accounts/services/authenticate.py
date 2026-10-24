from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.passwords import check_password, make_password, needs_rehash
from app.modules.accounts.exceptions import BadCredentials
from app.modules.accounts.models import User
from app.modules.accounts.selectors import user_by_email


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = user_by_email(db, email=email)
    if (
        user is None
        or not user.is_active
        or not check_password(password, user.password)
    ):
        raise BadCredentials
    if needs_rehash(user.password):
        user.password = make_password(password)
    user.last_login = utcnow()
    db.commit()
    return user
