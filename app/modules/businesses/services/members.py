"""The people of a business: who works in it, and what each may do.

A member is one person in one business. What they may read and change is a
set of grants, each naming an area (the adverts or the CRM), a network and a
level. A role is a ready set of grants and nothing more: picking it writes
the grants, and the owner may then change any of them.

    Targetolog       adverts, to change, on every network of the business
    Sotuv manageri   CRM, to change, on every network and on leads no
                     network brought; reads their own leads only
    ROP              a sales manager who also reads the other managers'
                     leads, in the networks the ROP holds a CRM grant on

The business's owner is never a member: the owner may do everything.

The cabinet's CRM still writes its managers into ``crm_members``;
:func:`mirror_crm_members` keeps a membership level with each of those.
"""

import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.businesses.constants import (
    OTHER_SOURCE,
    GrantArea,
    GrantLevel,
    MemberRole,
)
from app.modules.businesses.exceptions import (
    BadGrant,
    MemberExists,
    NotYourStaff,
    OwnerIsNotMember,
    RoleRequired,
    RopNeedsSales,
    UnknownRole,
)
from app.modules.businesses.models import (
    Business,
    BusinessLink,
    BusinessMember,
    BusinessMemberGrant,
)

Grants = dict[tuple[str, str], str]


def networks_of(db: Session, *, business_id: uuid.UUID) -> tuple[str, ...]:
    """The networks the business advertises on today, in a fixed order."""
    return tuple(
        db.scalars(
            select(BusinessLink.provider)
            .where(
                BusinessLink.business_id == business_id,
                BusinessLink.unbound_at.is_(None),
            )
            .distinct()
            .order_by(BusinessLink.provider)
        )
    )


def preset(*, roles: Iterable[str], networks: Iterable[str]) -> Grants:
    """The grants a set of roles starts with."""
    networks = tuple(networks)
    grants: Grants = {}
    chosen = set(roles)
    if MemberRole.TARGETOLOG in chosen:
        for network in networks:
            grants[(GrantArea.ADS, network)] = GrantLevel.EDIT
    if MemberRole.SALES in chosen:
        for network in (*networks, OTHER_SOURCE):
            grants[(GrantArea.CRM, network)] = GrantLevel.EDIT
    return grants


def _roles(roles: Iterable[str], *, is_rop: bool) -> list[str]:
    chosen = list(dict.fromkeys(str(role) for role in roles))
    if not chosen:
        raise RoleRequired
    if any(role not in MemberRole.values for role in chosen):
        raise UnknownRole
    if is_rop and MemberRole.SALES not in chosen:
        raise RopNeedsSales
    return sorted(chosen)


def _checked(
    grants: Mapping[tuple[str, str], str], *, networks: tuple[str, ...]
) -> Grants:
    checked: Grants = {}
    for (area, provider), level in grants.items():
        if area not in GrantArea.values:
            raise BadGrant("Bunday bo'lim yo'q.")
        if level not in GrantLevel.values:
            raise BadGrant("Ruxsat darajasi «ko'rish» yoki «o'zgartirish» bo'ladi.")
        if provider == OTHER_SOURCE:
            if area != GrantArea.CRM:
                raise BadGrant("«Boshqa manba» faqat CRM uchun beriladi.")
        elif provider not in networks:
            raise BadGrant("Bu tarmoq biznesga ulanmagan.")
        checked[(str(area), str(provider))] = str(level)
    return checked


def check(
    db: Session,
    *,
    business: Business,
    roles: Iterable[str],
    is_rop: bool,
    grants: Mapping[tuple[str, str], str] | None,
) -> None:
    """Raise what :func:`add_member` or :func:`change_member` would, and
    write nothing: for a caller with something to do before either."""
    _roles(roles, is_rop=is_rop)
    if grants is not None:
        _checked(grants, networks=networks_of(db, business_id=business.id))


def _write(member: BusinessMember, grants: Grants) -> None:
    held = {(grant.area, grant.provider): grant for grant in member.grants}
    for key, grant in held.items():
        if key not in grants:
            member.grants.remove(grant)
    for (area, provider), level in grants.items():
        grant = held.get((area, provider))
        if grant is None:
            member.grants.append(
                BusinessMemberGrant(area=area, provider=provider, level=level)
            )
        elif grant.level != level:
            grant.level = level


def add_member(
    db: Session,
    *,
    business: Business,
    user: User,
    roles: Iterable[str],
    is_rop: bool = False,
    grants: Mapping[tuple[str, str], str] | None = None,
    now: datetime | None = None,
) -> BusinessMember:
    """Put ``user`` to work in ``business``; flushes.

    ``grants`` given replaces the roles' ready set. A person the owner took
    out before comes back on the same row.
    """
    now = now or utcnow()
    if user.id == business.user_id:
        raise OwnerIsNotMember
    if user.crm_owner_id != business.user_id:
        raise NotYourStaff
    chosen = _roles(roles, is_rop=is_rop)
    networks = networks_of(db, business_id=business.id)
    wanted = (
        _checked(grants, networks=networks)
        if grants is not None
        else preset(roles=chosen, networks=networks)
    )
    member = db.scalar(
        select(BusinessMember)
        .where(
            BusinessMember.business_id == business.id,
            BusinessMember.user_id == user.id,
        )
        .with_for_update()
    )
    if member is not None and member.is_active:
        raise MemberExists
    if member is None:
        member = BusinessMember(
            business_id=business.id,
            owner_id=business.user_id,
            user_id=user.id,
            joined_at=now,
        )
        db.add(member)
    member.roles = chosen
    member.is_rop = is_rop
    member.is_active = True
    member.removed_at = None
    _write(member, wanted)
    db.flush()
    return member


def change_member(
    db: Session,
    *,
    member: BusinessMember,
    roles: Iterable[str],
    is_rop: bool,
    grants: Mapping[tuple[str, str], str] | None = None,
) -> BusinessMember:
    """New roles for a member. With no ``grants`` the roles' ready set
    replaces what the member held; with them, exactly those are kept."""
    chosen = _roles(roles, is_rop=is_rop)
    networks = networks_of(db, business_id=member.business_id)
    wanted = (
        _checked(grants, networks=networks)
        if grants is not None
        else preset(roles=chosen, networks=networks)
    )
    member.roles = chosen
    member.is_rop = is_rop
    _write(member, wanted)
    db.flush()
    return member


def remove_member(
    db: Session, *, member: BusinessMember, now: datetime | None = None
) -> BusinessMember:
    """Take the person out of the business. The row stays, with its grants,
    so their name still stands on what they did."""
    member.is_active = False
    member.removed_at = now or utcnow()
    db.flush()
    return member


def mirror_crm_members(db: Session, *, owner_id: uuid.UUID | None = None) -> int:
    """A membership for every CRM manager whose pair is a business; flushes.

    The manager's membership follows their CRM row: made with a sales
    manager's ready grants, moved when the manager is moved to another pair,
    switched off and on with them. A membership the owner has since given
    another role keeps its roles and grants, and only moves and switches.
    """
    from app.modules.crm.models import CrmMember

    query = select(CrmMember).where(CrmMember.business_id.is_not(None))
    if owner_id is not None:
        query = query.where(CrmMember.owner_id == owner_id)
    changed = 0
    for manager in db.scalars(query.order_by(CrmMember.created_at, CrmMember.id)):
        mirrored = db.scalar(
            select(BusinessMember).where(BusinessMember.crm_member_id == manager.id)
        )
        if mirrored is not None and mirrored.business_id != manager.business_id:
            mirrored.crm_member_id = None
            mirrored.is_active = False
            mirrored.removed_at = utcnow()
            db.flush()
            mirrored = None
            changed += 1
        if mirrored is None:
            mirrored = db.scalar(
                select(BusinessMember).where(
                    BusinessMember.business_id == manager.business_id,
                    BusinessMember.user_id == manager.user_id,
                )
            )
            if mirrored is None:
                mirrored = BusinessMember(
                    business_id=manager.business_id,
                    owner_id=manager.owner_id,
                    user_id=manager.user_id,
                    roles=[MemberRole.SALES.value],
                    joined_at=manager.created_at,
                    is_active=manager.is_active,
                )
                db.add(mirrored)
                _write(
                    mirrored,
                    preset(
                        roles=[MemberRole.SALES],
                        networks=networks_of(db, business_id=manager.business_id),
                    ),
                )
            mirrored.crm_member_id = manager.id
            changed += 1
        if mirrored.is_active != manager.is_active:
            mirrored.is_active = manager.is_active
            mirrored.removed_at = None if manager.is_active else utcnow()
            changed += 1
        db.flush()
    return changed + _drop_left_sales(db, owner_id=owner_id)


def _drop_left_sales(db: Session, *, owner_id: uuid.UUID | None) -> int:
    """A sales manager the CRM has taken off the pair stops being one here:
    a member who is a targetolog as well keeps that role and its grants, and
    anybody else leaves the business."""
    from app.modules.crm.models import CrmMember

    works = (
        select(CrmMember.id)
        .where(
            CrmMember.business_id == BusinessMember.business_id,
            CrmMember.user_id == BusinessMember.user_id,
            CrmMember.is_active.is_(True),
        )
        .exists()
    )
    query = select(BusinessMember).where(
        BusinessMember.is_active.is_(True),
        BusinessMember.crm_member_id.is_(None),
        ~works,
    )
    if owner_id is not None:
        query = query.where(BusinessMember.owner_id == owner_id)
    dropped = 0
    for member in db.scalars(query):
        if MemberRole.SALES not in member.roles:
            continue
        if MemberRole.TARGETOLOG in member.roles:
            member.roles = [MemberRole.TARGETOLOG.value]
            member.is_rop = False
            _write(
                member,
                {
                    (grant.area, grant.provider): grant.level
                    for grant in member.grants
                    if grant.area != GrantArea.CRM
                },
            )
        else:
            member.is_active = False
            member.removed_at = utcnow()
        dropped += 1
    db.flush()
    return dropped
