"""Staff and their roles, version 2: find a signed-up account, make it
staff with roles, change the roles, take it off. The office journal and
the rules of the staff services stay the same: nobody changes their own
standing and the superuser's roles are fixed. Only the superuser gives or
takes the Owner role."""

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError, NotFound
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ROLE_LABELS, Role
from app.modules.backoffice.permissions import roles_of
from app.modules.boards.constants import SEARCH_MAX

SEARCH_ROWS = 20


class StaffNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("Xodim topilmadi.")


class AccountNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("Bunday ro'yxatdan o'tgan foydalanuvchi yo'q.")


class UnknownRole(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bunday rol yo'q.")


class OwnerRoleSuperuserOnly(DomainError):
    status_code = 403

    def __init__(self) -> None:
        super().__init__("Egasi rolini faqat superuser beradi va oladi.")


def _roles(values: list[str]) -> list[Role]:
    if any(value not in Role.values for value in values):
        raise UnknownRole
    return [Role(value) for value in dict.fromkeys(values)]


def _person(db: Session, user: User) -> dict[str, Any]:
    held = roles_of(db, user) if user.is_staff else frozenset()
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
        "phone": user.phone,
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
        "roles": [
            {"value": str(role), "label": str(ROLE_LABELS[role])}
            for role in Role
            if str(role) in held
        ],
    }


def staff_list(db: Session) -> list[dict[str, Any]]:
    people = db.scalars(
        select(User)
        .where(User.is_staff.is_(True), User.is_active.is_(True))
        .order_by(User.is_superuser.desc(), User.full_name, User.email)
    )
    return [_person(db, person) for person in people]


def search_accounts(db: Session, *, q: str) -> list[dict[str, Any]]:
    """Signed-up accounts that are not staff yet, by email, phone or name.
    A CRM login belongs to its owner's business, so it is not offered."""
    words = q.strip()[:SEARCH_MAX]
    if len(words) < 3:
        return []
    like = f"%{words}%"
    people = db.scalars(
        select(User)
        .where(
            User.is_staff.is_(False),
            User.is_active.is_(True),
            User.crm_owner_id.is_(None),
            or_(
                User.email.ilike(like),
                User.phone.ilike(like),
                User.full_name.ilike(like),
            ),
        )
        .order_by(User.date_joined.desc())
        .limit(SEARCH_ROWS)
    )
    return [_person(db, person) for person in people]


def _guard_owner(db: Session, *, member: User, wanted: list[Role], actor: User) -> None:
    held = roles_of(db, member) if member.is_staff else frozenset()
    touches = (str(Role.OWNER) in held) != (Role.OWNER in wanted)
    if touches and not actor.is_superuser:
        raise OwnerRoleSuperuserOnly


def _member(db: Session, member_id: uuid.UUID) -> User:
    member = db.get(User, member_id)
    if member is None or not member.is_staff:
        raise StaffNotFound
    return member


def add_staff(
    db: Session, *, user_id: uuid.UUID, roles: list[str], actor: User
) -> dict[str, Any]:
    account = db.get(User, user_id)
    if account is None:
        raise AccountNotFound
    wanted = _roles(roles)
    _guard_owner(db, member=account, wanted=wanted, actor=actor)
    from app.modules.backoffice.services.roles import add_member, set_roles

    member = add_member(db, email=account.email, actor=actor)
    set_roles(db, member=member, roles=wanted, actor=actor)
    db.commit()
    return _person(db, member)


def change_roles(
    db: Session, *, member_id: uuid.UUID, roles: list[str], actor: User
) -> dict[str, Any]:
    member = _member(db, member_id)
    wanted = _roles(roles)
    _guard_owner(db, member=member, wanted=wanted, actor=actor)
    from app.modules.backoffice.services.roles import set_roles

    set_roles(db, member=member, roles=wanted, actor=actor)
    db.commit()
    return _person(db, member)


def remove_staff(db: Session, *, member_id: uuid.UUID, actor: User) -> None:
    member = _member(db, member_id)
    _guard_owner(db, member=member, wanted=[], actor=actor)
    # Imported here: the staff services import the office package, which
    # imports the support chat, which imports the office services back.
    from app.modules.backoffice.services.roles import remove_member

    remove_member(db, member=member, actor=actor)
    db.commit()
