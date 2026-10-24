from sqlalchemy.orm import Session

from app.modules.accounts.constants import Language
from app.modules.accounts.exceptions import UnsupportedLanguage
from app.modules.accounts.models import User


def set_language(db: Session, *, user: User, language: str) -> User:
    if language not in {item.value for item in Language}:
        raise UnsupportedLanguage
    user.language = language
    db.commit()
    return user
