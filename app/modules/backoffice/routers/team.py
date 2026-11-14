"""Jamoa, as JSON: who is on the staff and what each of them may open.

Owner only. A person outside the staff is 404 here, however their id was come by.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import Db
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import Role
from app.modules.backoffice.exceptions import OwnerRoleSuperuserOnly
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.schemas import (
    MessageOut,
    StaffFoundOut,
    StaffMemberOut,
    StaffTeamOut,
)
from app.modules.backoffice.selectors.team import (
    Member,
    member_by_id,
    members,
    search_accounts,
)

router = APIRouter(prefix="/team")
Owner = Annotated[User, Depends(staff_required(Role.OWNER))]


class StaffRolesIn(BaseModel):
    roles: list[Role]


class StaffMemberIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    roles: list[Role] = Field(
        default_factory=list, description="Given at once; empty: no roles yet."
    )


def member_out(member: Member, *, reader: User) -> dict[str, Any]:
    return {
        "id": str(member.user.id),
        "name": member.user.full_name or member.user.email,
        "email": member.user.email,
        "phone": member.user.phone,
        "roles": member.roles,
        "superuser": member.user.is_superuser,
        "is_me": member.user.id == reader.id,
    }


def _one(db: Db, member_id: uuid.UUID) -> User:
    member = member_by_id(db, member_id=member_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return member


@router.get("", responses={200: {"model": StaffTeamOut}})
def team(db: Db, user: Owner) -> dict[str, Any]:
    """Everybody on the staff, super admins first."""
    return {"members": [member_out(member, reader=user) for member in members(db)]}


@router.post("", responses={200: {"model": StaffMemberOut}})
def add(db: Db, user: Owner, body: StaffMemberIn) -> dict[str, Any]:
    """Bring an account onto the staff, with these roles or with none yet."""
    if Role.OWNER in body.roles and not user.is_superuser:
        raise OwnerRoleSuperuserOnly
    member = services.add_member(db, email=body.email, actor=user)
    roles = (
        services.set_roles(db, member=member, roles=body.roles, actor=user)
        if body.roles
        else []
    )
    db.commit()
    return member_out(Member(user=member, roles=roles), reader=user)


@router.get("/search", responses={200: {"model": StaffFoundOut}})
def search(
    db: Db, user: Owner, q: Annotated[str, Query(min_length=3, max_length=100)]
) -> dict[str, Any]:
    """Signed-up accounts not on the staff yet, by email, phone or name."""
    return {"people": search_accounts(db, q=q)}


@router.post("/{member_id}/roles", responses={200: {"model": StaffMemberOut}})
def save_roles(
    db: Db, user: Owner, member_id: uuid.UUID, body: StaffRolesIn
) -> dict[str, Any]:
    """Replace this member's roles with exactly these."""
    member = _one(db, member_id)
    roles = services.set_roles(db, member=member, roles=body.roles, actor=user)
    db.commit()
    return member_out(Member(user=member, roles=roles), reader=user)


@router.post("/{member_id}/remove", responses={200: {"model": MessageOut}})
def remove(db: Db, user: Owner, member_id: uuid.UUID) -> dict[str, str]:
    """Take this person off the staff; their account goes on as a customer's."""
    services.remove_member(db, member=_one(db, member_id), actor=user)
    db.commit()
    return {"message": "Xodim jamoadan chiqarildi."}
