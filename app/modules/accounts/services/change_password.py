from sqlalchemy.orm import Session

from app.common.passwords import check_password, make_password
from app.modules.accounts.exceptions import WrongPassword
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit


def change_password(
    db: Session, *, user: User, current_password: str, new_password: str
) -> User:
    if not check_password(current_password, user.password):
        raise WrongPassword
    user.password = make_password(new_password)
    emit(
        db,
        owner_id=user.id,
        name=EventName.USER_PASSWORD_CHANGED,
        aggregate_type="user",
        aggregate_id=user.id,
    )
    db.commit()
    return user
