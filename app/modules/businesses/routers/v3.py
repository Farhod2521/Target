"""``/api/v3/businesses``: the business as the thing a person works in.

Every route below asks :func:`access_for` first. The owner may do
everything; a member reads the business they work in; anybody else is
answered 404, as for a business that does not exist. The people of a
business are the owner's to read and change.
"""

import uuid
from collections.abc import Iterable

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.businesses import selectors
from app.modules.businesses.constants import (
    GRANT_AREA_LABELS,
    GRANT_LEVEL_LABELS,
    MEMBER_ROLE_LABELS,
    OTHER_SOURCE,
    GrantArea,
    GrantLevel,
    MemberRole,
)
from app.modules.businesses.exceptions import (
    LoginRequired,
    ManagedByCrm,
    NoSeat,
    NotYourStaff,
    SalesThroughCrm,
    UnknownMember,
)
from app.modules.businesses.models import Business, BusinessLink, BusinessMember
from app.modules.businesses.routers import _out as profile_out
from app.modules.businesses.schemas.v3 import (
    AccessOut,
    AccountOut,
    BusinessCardOut,
    BusinessDetailOut,
    BusinessListOut,
    CatalogOut,
    ChoiceOut,
    GrantIn,
    GrantOut,
    MemberIn,
    MemberOut,
    MemberPatch,
    MembersOut,
    NetworkOut,
    PageOut,
    PersonOut,
    RoleOut,
    SeatsOut,
)
from app.modules.businesses.selectors.access import (
    Access,
    access_for,
    businesses_of,
    members_of,
    seats_taken,
)
from app.modules.businesses.services import members as member_services
from app.modules.businesses.services.members import networks_of, preset

router = APIRouter(prefix="/businesses", tags=["businesses v3"])

EVERY_NETWORK = "*"


def _grants(pairs: Iterable[tuple[tuple[str, str], str]]) -> list[GrantOut]:
    return [
        GrantOut(area=area, provider=provider, level=level)  # type: ignore[arg-type]
        for (area, provider), level in sorted(pairs)
    ]


def _access(access: Access) -> AccessOut:
    member = access.member
    return AccessOut(
        is_owner=access.is_owner,
        roles=list(member.roles) if member is not None else [],
        is_rop=access.is_rop,
        reads_all_leads=access.reads_all_leads,
        grants=_grants(access.grants.items()),
    )


def _networks(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[NetworkOut]]:
    found: dict[uuid.UUID, list[NetworkOut]] = {one: [] for one in ids}
    if not ids:
        return found
    for link in db.scalars(
        select(BusinessLink)
        .where(BusinessLink.business_id.in_(ids), BusinessLink.unbound_at.is_(None))
        .order_by(BusinessLink.provider, BusinessLink.bound_at)
    ):
        page, account = link.page, link.ad_account
        found[link.business_id].append(
            NetworkOut(
                provider=link.provider,
                kind=link.kind,
                pair=link.external_id,
                page=PageOut(
                    id=page.id,
                    external_id=page.external_id,
                    name=page.name,
                    instagram_username=page.instagram_username,
                )
                if page is not None
                else None,
                ad_account=AccountOut(
                    id=account.id,
                    external_id=account.external_id,
                    name=account.name,
                    currency=account.currency,
                )
                if account is not None
                else None,
                bound_at=link.bound_at,
            )
        )
    return found


def _card(access: Access, networks: list[NetworkOut]) -> dict[str, object]:
    business = access.business
    return {
        "id": business.id,
        "name": business.name,
        "category_label": selectors.category_label(business),
        "city": business.city,
        "networks": networks,
        "access": _access(access),
    }


@router.get("", response_model=BusinessListOut)
def list_businesses(db: Db, user: CurrentUser) -> BusinessListOut:
    """The businesses this person switches between: the ones they own that
    advertise from something, and the ones they work in."""
    rows = businesses_of(db, user=user)
    networks = _networks(db, [row.id for row in rows])
    return BusinessListOut(
        businesses=[
            BusinessCardOut(
                **_card(access_for(db, business_id=row.id, user=user), networks[row.id])
            )
            for row in rows
        ]
    )


@router.get("/catalog", response_model=CatalogOut)
def catalog(user: CurrentUser) -> CatalogOut:
    """The roles, areas and levels the member form offers."""
    return CatalogOut(
        roles=[
            RoleOut(
                key=role.value,  # type: ignore[arg-type]
                label=MEMBER_ROLE_LABELS[role],
                may_be_rop=role == MemberRole.SALES,
                grants=_grants(preset(roles=[role], networks=[EVERY_NETWORK]).items()),
            )
            for role in MemberRole
        ],
        areas=[
            ChoiceOut(key=area.value, label=GRANT_AREA_LABELS[area])
            for area in GrantArea
        ],
        levels=[
            ChoiceOut(key=level.value, label=GRANT_LEVEL_LABELS[level])
            for level in GrantLevel
        ],
        other_source=ChoiceOut(key=OTHER_SOURCE, label="Boshqa manba"),
    )


@router.get("/{business_id}", response_model=BusinessDetailOut)
def business(business_id: uuid.UUID, db: Db, user: CurrentUser) -> BusinessDetailOut:
    access = access_for(db, business_id=business_id, user=user)
    profile = profile_out(access.business)
    assert profile is not None
    return BusinessDetailOut(
        **_card(access, _networks(db, [business_id])[business_id]),
        profile=profile,
        members_count=len(members_of(db, business_id=business_id))
        if access.is_owner
        else None,
    )


def _person(user: User) -> PersonOut:
    return PersonOut(id=user.id, full_name=user.full_name, email=user.email)


def _member_out(member: BusinessMember) -> MemberOut:
    return MemberOut(
        id=member.id,
        user=_person(member.user),
        roles=list(member.roles),
        is_rop=member.is_rop,
        is_active=member.is_active,
        joined_at=member.joined_at,
        removed_at=member.removed_at,
        from_crm=member.crm_member_id is not None,
        grants=_grants(
            ((grant.area, grant.provider), grant.level) for grant in member.grants
        ),
    )


def _seats(db: Session, *, owner: User) -> SeatsOut:
    from app.modules.crm.selectors import seat_capacity

    taken = seats_taken(db, owner_id=owner.id)
    capacity = seat_capacity(db, owner=owner, at=utcnow())
    return SeatsOut(taken=taken, capacity=capacity, free=max(0, capacity - taken))


def _members(db: Session, *, business: Business, owner: User) -> MembersOut:
    members = members_of(db, business_id=business.id)
    here = {member.user_id for member in members}
    candidates = db.scalars(
        select(User)
        .where(User.crm_owner_id == owner.id, User.is_active.is_(True))
        .order_by(User.full_name, User.email)
    )
    return MembersOut(
        members=[_member_out(member) for member in members],
        seats=_seats(db, owner=owner),
        candidates=[_person(one) for one in candidates if one.id not in here],
        networks=list(networks_of(db, business_id=business.id)),
    )


def _owner_access(db: Session, business_id: uuid.UUID, user: User) -> Access:
    access = access_for(db, business_id=business_id, user=user)
    access.require_owner()
    return access


def _asked(grants: list[GrantIn] | None) -> dict[tuple[str, str], str] | None:
    if grants is None:
        return None
    return {(grant.area, grant.provider): grant.level for grant in grants}


def _works_the_crm(db: Session, *, business: Business, user_id: uuid.UUID) -> bool:
    from app.modules.crm.models import CrmMember

    return bool(
        db.scalar(
            select(CrmMember.id).where(
                CrmMember.business_id == business.id,
                CrmMember.user_id == user_id,
                CrmMember.is_active.is_(True),
            )
        )
    )


def _check_sales(
    db: Session, *, business: Business, user_id: uuid.UUID | None, roles: list[str]
) -> None:
    """A sales manager works the CRM, whose managers the CRM section still
    adds: the role is given here only to somebody it has added."""
    if MemberRole.SALES not in roles:
        return
    if user_id is None or not _works_the_crm(db, business=business, user_id=user_id):
        raise SalesThroughCrm


@router.get("/{business_id}/members", response_model=MembersOut)
def list_members(business_id: uuid.UUID, db: Db, user: CurrentUser) -> MembersOut:
    access = _owner_access(db, business_id, user)
    return _members(db, business=access.business, owner=user)


@router.post(
    "/{business_id}/members",
    response_model=MembersOut,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    business_id: uuid.UUID, body: MemberIn, db: Db, user: CurrentUser
) -> MembersOut:
    """One of the owner's people, or a new login, put to work here."""
    from app.modules.accounts.services import create_member_login
    from app.modules.crm.services import check_email, check_password

    access = _owner_access(db, business_id, user)
    business = access.business
    _check_sales(db, business=business, user_id=body.user_id, roles=list(body.roles))
    if _seats(db, owner=user).free < 1:
        raise NoSeat
    if body.user_id is not None:
        person = db.get(User, body.user_id)
        if person is None or person.crm_owner_id != user.id:
            raise NotYourStaff
    else:
        name, email = body.name.strip(), body.email.strip().lower()
        if not (name and email and body.password):
            raise LoginRequired
        check_email(email)
        check_password(password=body.password, email=email, full_name=name)
        person = create_member_login(
            db, owner=user, email=email, full_name=name, password=body.password
        )
    member_services.add_member(
        db,
        business=business,
        user=person,
        roles=body.roles,
        is_rop=body.is_rop,
        grants=_asked(body.grants),
    )
    db.commit()
    return _members(db, business=business, owner=user)


def _member(db: Session, *, business: Business, member_id: uuid.UUID) -> BusinessMember:
    member = db.scalar(
        select(BusinessMember).where(
            BusinessMember.id == member_id,
            BusinessMember.business_id == business.id,
            BusinessMember.is_active.is_(True),
        )
    )
    if member is None:
        raise UnknownMember
    return member


@router.patch("/{business_id}/members/{member_id}", response_model=MembersOut)
def change_member(
    business_id: uuid.UUID,
    member_id: uuid.UUID,
    body: MemberPatch,
    db: Db,
    user: CurrentUser,
) -> MembersOut:
    """New roles for a member. With no ``grants`` the roles' ready set
    replaces what they held; with them, exactly those are kept."""
    access = _owner_access(db, business_id, user)
    member = _member(db, business=access.business, member_id=member_id)
    _check_sales(
        db, business=access.business, user_id=member.user_id, roles=list(body.roles)
    )
    if member.crm_member_id is not None and MemberRole.SALES not in body.roles:
        raise ManagedByCrm
    member_services.change_member(
        db,
        member=member,
        roles=body.roles,
        is_rop=body.is_rop,
        grants=_asked(body.grants),
    )
    db.commit()
    return _members(db, business=access.business, owner=user)


@router.delete("/{business_id}/members/{member_id}", response_model=MembersOut)
def remove_member(
    business_id: uuid.UUID, member_id: uuid.UUID, db: Db, user: CurrentUser
) -> MembersOut:
    access = _owner_access(db, business_id, user)
    member = _member(db, business=access.business, member_id=member_id)
    if member.crm_member_id is not None:
        raise ManagedByCrm
    member_services.remove_member(db, member=member)
    db.commit()
    return _members(db, business=access.business, owner=user)
