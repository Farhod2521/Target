from collections.abc import Callable, Iterable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.common.db import get_db
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.backoffice.constants import Role


def has_role(db: Session, user: User | None, roles: Iterable[Role | str]) -> bool:
    if user is None or not user.is_active or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    wanted = {str(role) for role in roles}
    return (
        db.scalar(
            select(Group.id)
            .join(UserGroup, UserGroup.group_id == Group.id)
            .where(UserGroup.user_id == user.id, Group.name.in_(wanted))
            .limit(1)
        )
        is not None
    )


def roles_of(db: Session, user: User | None) -> frozenset[str]:
    if user is None or not user.is_staff:
        return frozenset()
    names = [str(role) for role in Role]
    if user.is_superuser:
        return frozenset(names)
    return frozenset(
        db.scalars(
            select(Group.name)
            .join(UserGroup, UserGroup.group_id == Group.id)
            .where(UserGroup.user_id == user.id, Group.name.in_(names))
        )
    )


def staff_required(*roles: Role) -> Callable[..., User]:
    """A dependency that lets through only staff holding one of ``roles``.

    The refusal is a 404, as in Django: an office screen is not admitted to
    by somebody who may not open it.
    """
    if not roles:
        raise ValueError("staff_required needs at least one role")

    def guard(
        user: User = Depends(current_user), db: Session = Depends(get_db)
    ) -> User:
        if not has_role(db, user, roles):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return user

    return guard
