"""Who is on the staff, and which half of the console each of them may open.

Nobody may change their own standing: an owner who removes their own last role
locks the console, and the way back is a shell on the database. A super admin
holds every role whatever the groups say, so theirs are not edited here at all.

Being on the staff takes an account out of the customer lists, the sales pool
and the surveys, so taking somebody off gives them back to all of those.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import Group, User, UserGroup
from app.modules.accounts.selectors import user_by_email
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.exceptions import (
    AlreadyStaff,
    CannotChangeOwnRoles,
    StaffAccountClosed,
    StaffAccountMissing,
    SuperuserRolesFixed,
)
from app.modules.backoffice.services.journal import record


def _editable(member: User, actor: User) -> None:
    if member.id == actor.id:
        raise CannotChangeOwnRoles
    if member.is_superuser:
        raise SuperuserRolesFixed


def _groups(db: Session) -> dict[str, Group]:
    """Every role's group, made if the copied database never had it: a box that
    ticks and then does nothing is worse than a row nobody seeded."""
    names = [str(role) for role in Role]
    found = {
        group.name: group
        for group in db.scalars(select(Group).where(Group.name.in_(names)))
    }
    for name in names:
        if name not in found:
            found[name] = Group(name=name)
            db.add(found[name])
    db.flush()
    return found


def _held(db: Session, member: User, groups: dict[str, Group]) -> set[str]:
    return set(
        db.scalars(
            select(Group.name)
            .join(UserGroup, UserGroup.group_id == Group.id)
            .where(UserGroup.user_id == member.id, Group.name.in_(groups))
        )
    )


def _drop(db: Session, member: User, groups: list[Group]) -> None:
    db.execute(
        delete(UserGroup).where(
            UserGroup.user_id == member.id,
            UserGroup.group_id.in_([group.id for group in groups]),
        )
    )


def set_roles(
    db: Session, *, member: User, roles: list[Role], actor: User
) -> list[str]:
    """The screen shows every role with a box, so what it sends is the whole
    answer. Groups this console does not know are left alone."""
    _editable(member, actor)
    groups = _groups(db)
    wanted = {str(role) for role in roles}
    held = _held(db, member, groups)
    _drop(db, member, [groups[name] for name in held - wanted])
    db.add_all(
        UserGroup(user_id=member.id, group_id=groups[name].id) for name in wanted - held
    )
    db.flush()
    after = sorted(wanted)
    record(
        db,
        customer=member,
        actor=actor,
        kind=ActionKind.ROLES_CHANGED,
        detail={"from": sorted(held), "to": after},
    )
    return after


def add_member(db: Session, *, email: str, actor: User) -> User:
    """An account that exists already, with no roles yet: it opens nothing until
    the boxes are ticked."""
    member = user_by_email(db, email=email)
    if member is None:
        raise StaffAccountMissing
    if member.is_staff:
        raise AlreadyStaff
    if not member.is_active:
        raise StaffAccountClosed
    member.is_staff = True
    db.flush()
    record(db, customer=member, actor=actor, kind=ActionKind.STAFF_ADDED)
    return member


def remove_member(db: Session, *, member: User, actor: User) -> None:
    """The bot link stays on its row but carries nothing: every send and every
    reply asks for the role first."""
    _editable(member, actor)
    groups = _groups(db)
    held = _held(db, member, groups)
    _drop(db, member, [groups[name] for name in held])
    member.is_staff = False
    db.flush()
    record(
        db,
        customer=member,
        actor=actor,
        kind=ActionKind.STAFF_REMOVED,
        detail={"from": sorted(held)},
    )
