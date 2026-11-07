from sqlalchemy.orm import Session

from app.modules.accounts.constants import Language, Role
from app.modules.accounts.exceptions import UnsupportedLanguage
from app.modules.accounts.models import User


def set_language(db: Session, *, user: User, language: str) -> User:
    if language not in {item.value for item in Language}:
        raise UnsupportedLanguage
    user.language = language
    db.commit()
    return user


def set_expert_mode(db: Session, *, user: User, on: bool) -> User:
    user.expert_mode = on
    db.commit()
    return user


def set_role(db: Session, *, user: User, role: Role) -> User:
    """Who the owner says they are; asked once of accounts opened before the
    question, and changeable from the profile."""
    user.role = role.value
    db.commit()
    return user
