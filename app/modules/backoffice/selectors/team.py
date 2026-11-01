"""The office's roster."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import Group, User, UserGroup
from app.modules.backoffice.constants import Role


@dataclass(frozen=True, slots=True)
class Member:
    user: User
    roles: list[str]


def members(db: Session) -> list[Member]:
    people = db.scalars(
        select(User)
        .where(User.is_staff.is_(True))
        .order_by(User.is_superuser.desc(), User.email)
    ).all()
    names = [str(role) for role in Role]
    held: dict[uuid.UUID, set[str]] = {}
    for user_id, name in db.execute(
        select(UserGroup.user_id, Group.name)
        .join(Group, Group.id == UserGroup.group_id)
        .where(Group.name.in_(names))
    ):
        held.setdefault(user_id, set()).add(name)
    return [
        Member(
            user=person,
            roles=names
            if person.is_superuser
            else [name for name in names if name in held.get(person.id, ())],
        )
        for person in people
    ]


def member_by_id(db: Session, *, member_id: uuid.UUID) -> User | None:
    """Narrowed to the staff: the roster cannot hand a customer a role."""
    return db.scalar(select(User).where(User.id == member_id, User.is_staff.is_(True)))
