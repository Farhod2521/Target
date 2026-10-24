from typing import Any

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit


def block_user(
    db: Session, *, user: User, reason: str, details: dict[str, Any] | None = None
) -> User:
    if not user.is_active:
        return user
    user.is_active = False
    emit(
        db,
        owner_id=user.id,
        name=EventName.USER_BLOCKED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"reason": reason, **(details or {})},
    )
    db.flush()
    return user
