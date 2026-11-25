"""What a signed-in person may do in a business.

One question, asked by every read and write that works on a business: the
owner may do everything; a member, what their grants say; anybody else,
nothing, and is told the business does not exist.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.businesses.constants import GrantLevel
from app.modules.businesses.exceptions import NoAccess, UnknownBusiness
from app.modules.businesses.models import Business, BusinessLink, BusinessMember

_RANK = {GrantLevel.VIEW.value: 1, GrantLevel.EDIT.value: 2}


@dataclass(frozen=True, slots=True)
class Access:
    business: Business
    user: User
    member: BusinessMember | None = None
    grants: Mapping[tuple[str, str], str] = field(default_factory=dict)

    @property
    def is_owner(self) -> bool:
        return self.member is None

    @property
    def is_rop(self) -> bool:
        return self.member is not None and bool(self.member.is_rop)

    @property
    def reads_all_leads(self) -> bool:
        """Whether the leads of other managers are theirs to read too."""
        return self.is_owner or self.is_rop

    def may(self, area: str, provider: str, level: str = GrantLevel.VIEW) -> bool:
        if self.is_owner:
            return True
        held = self.grants.get((str(area), str(provider)))
        return held is not None and _RANK[held] >= _RANK[str(level)]

    def networks(self, area: str, level: str = GrantLevel.VIEW) -> frozenset[str]:
        """The networks (and ``other``) of ``area`` this person reaches.
        For the owner the set is not listed: ask :meth:`may`."""
        return frozenset(
            provider
            for (held_area, provider), held in self.grants.items()
            if held_area == str(area) and _RANK[held] >= _RANK[str(level)]
        )

    def reaches(self, area: str, level: str = GrantLevel.VIEW) -> bool:
        return self.is_owner or bool(self.networks(area, level))

    def require(self, area: str, provider: str, level: str = GrantLevel.VIEW) -> None:
        if not self.may(area, provider, level):
            raise NoAccess

    def require_owner(self) -> None:
        if not self.is_owner:
            raise NoAccess


def access_for(db: Session, *, business_id: uuid.UUID, user: User) -> Access:
    """Raises :class:`UnknownBusiness` for a business that is not this
    person's to see, whether or not it exists."""
    business = db.get(Business, business_id)
    if business is None:
        raise UnknownBusiness
    if business.user_id == user.id:
        return Access(business=business, user=user)
    member = db.scalar(
        select(BusinessMember).where(
            BusinessMember.business_id == business.id,
            BusinessMember.user_id == user.id,
            BusinessMember.is_active.is_(True),
        )
    )
    if member is None:
        raise UnknownBusiness
    return Access(
        business=business,
        user=user,
        member=member,
        grants={(grant.area, grant.provider): grant.level for grant in member.grants},
    )


def businesses_of(db: Session, *, user: User) -> list[Business]:
    """The businesses a person switches between: the ones they own that
    advertise from something, and the ones they work in."""
    linked = select(BusinessLink.business_id).where(BusinessLink.unbound_at.is_(None))
    works_in = select(BusinessMember.business_id).where(
        BusinessMember.user_id == user.id, BusinessMember.is_active.is_(True)
    )
    return list(
        db.scalars(
            select(Business)
            .where(
                or_(
                    Business.id.in_(works_in),
                    (Business.user_id == user.id) & Business.id.in_(linked),
                )
            )
            .order_by(Business.name, Business.created_at, Business.id)
        )
    )


def members_of(
    db: Session, *, business_id: uuid.UUID, active_only: bool = True
) -> list[BusinessMember]:
    query = select(BusinessMember).where(BusinessMember.business_id == business_id)
    if active_only:
        query = query.where(BusinessMember.is_active.is_(True))
    return list(db.scalars(query.order_by(BusinessMember.joined_at, BusinessMember.id)))


def seats_taken(db: Session, *, owner_id: uuid.UUID) -> int:
    """One seat for every person in every business of the owner's."""
    return len(
        db.execute(
            select(BusinessMember.id).where(
                BusinessMember.owner_id == owner_id,
                BusinessMember.is_active.is_(True),
            )
        ).all()
    )


__all__ = [
    "Access",
    "access_for",
    "businesses_of",
    "members_of",
    "seats_taken",
]
