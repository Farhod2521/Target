from typing import Any

from sqlalchemy.orm import Session

from app.modules.backoffice.constants import ANSWER_ROLES, Role
from app.modules.backoffice.permissions import has_role


def may_answer_support(db: Session, *, user: Any) -> bool:
    return has_role(db, user, ANSWER_ROLES)


def may_read_faults(db: Session, *, user: Any) -> bool:
    return has_role(db, user, (Role.ENGINEER,))


def holds_any_role(db: Session, *, user: Any) -> bool:
    return has_role(db, user, tuple(Role))
