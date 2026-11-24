import uuid
from collections.abc import Callable, Iterable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.common.db import get_db
from app.modules.accounts.models import Group, User, UserGroup
from app.modules.backoffice.constants import ADMIN_ROLES, Role


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


def superuser_required(user: User = Depends(current_user)) -> User:
    """A dependency for the superuser alone: no role opens this door."""
    if not (user.is_active and user.is_staff and user.is_superuser):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return user


def reads_whole_office(db: Session, user: User) -> bool:
    """Support, Finance, the Owner and the superuser: every client's card."""
    return has_role(db, user, ADMIN_ROLES)


def customer_reader(
    customer_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> User:
    """Who may read this client's card. Support, Finance and the Owner read
    any; somebody of Sales reads only a client whose Sales card they may
    open on the board (a manager their own, the lead the team's), and only
    reads. Anybody else gets the office's 404."""
    if reads_whole_office(db, user):
        return user
    if not (user.is_active and user.is_staff):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Imported here: the boards read the office's roles.
    from app.modules.boards.client import sells_to

    if not sells_to(db, user=user, client_id=customer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return user
