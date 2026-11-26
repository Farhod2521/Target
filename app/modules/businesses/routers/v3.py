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
from app.modules.audit.constants import EVENT_NAME_LABELS, EventName
from app.modules.audit.models import Event
from app.modules.businesses import selectors
from app.modules.businesses.constants import (
    GRANT_AREA_LABELS,
    GRANT_LEVEL_LABELS,
    MEMBER_ROLE_LABELS,
    OTHER_SOURCE,
    GrantArea,
    GrantLevel,
    LinkKind,
    MemberRole,
)
from app.modules.businesses.exceptions import (
    LoginRequired,
    MemberExists,
    NoPairForCrm,
    NoSeat,
    NotYourStaff,
    UnknownMember,
)
from app.modules.businesses.models import Business, BusinessLink, BusinessMember
from app.modules.businesses.routers import _out as profile_out
from app.modules.businesses.schemas.v3 import (
    AccessOut,
    AccountChoiceOut,
    AccountOut,
    BusinessCardOut,
    BusinessDetailOut,
    BusinessListOut,
    CatalogOut,
    ChoiceOut,
    GrantIn,
    GrantOut,
    HistoryItemOut,
    HistoryOut,
    HistoryPersonOut,
    MemberIn,
    MemberOut,
    MemberPatch,
    MembersOut,
    NetworkIn,
    NetworkOut,
    NetworksOut,
    PageOut,
    PersonOut,
    RoleOut,
    SeatsOut,
    StandingOut,
)
from app.modules.businesses.selectors.access import (
    Access,
    access_for,
    businesses_of,
    members_of,
    seats_taken,
)
from app.modules.businesses.services import members as member_services
from app.modules.businesses.services import networks as network_services
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


def _crm_owner(db: Session, *, business: Business, owner: User):  # type: ignore[no-untyped-def]
    """The owner on this business's pair of the CRM, whose managers a sales
    manager is one of."""
    from app.modules.crm.selectors import viewer_for

    key = db.scalar(
        select(BusinessLink.external_id).where(
            BusinessLink.business_id == business.id,
            BusinessLink.kind == LinkKind.META_PAIR,
            BusinessLink.unbound_at.is_(None),
        )
    )
    viewer = viewer_for(db, user=owner, wanted=key or "")
    if key is None or viewer.pair is None or viewer.pair.key != key:
        raise NoPairForCrm
    return viewer


def _manager_row(db: Session, *, business: Business, user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    from app.modules.crm.models import CrmMember

    return db.scalar(
        select(CrmMember).where(
            CrmMember.business_id == business.id,
            CrmMember.user_id == user_id,
            CrmMember.is_active.is_(True),
        )
    )


def _mirrored(db: Session, *, business: Business, user_id: uuid.UUID) -> BusinessMember:
    """The membership the CRM's new manager row was just given."""
    db.flush()
    member_services.mirror_crm_members(db, owner_id=business.user_id)
    member = db.scalar(
        select(BusinessMember).where(
            BusinessMember.business_id == business.id,
            BusinessMember.user_id == user_id,
        )
    )
    if member is None:
        raise UnknownMember
    return member


def _leave_crm(
    db: Session, *, business: Business, owner: User, user_id: uuid.UUID
) -> None:
    """Take the person off this business's CRM: their cards go back to the
    board, and the login stays while they have other work."""
    from app.modules.crm.services import remove_member as remove_manager

    row = _manager_row(db, business=business, user_id=user_id)
    if row is None:
        return
    remove_manager(
        db, viewer=_crm_owner(db, business=business, owner=owner), member_id=str(row.id)
    )
    # The removal deletes around the session; what it holds of the person's
    # rows is read again.
    db.flush()
    db.expire_all()


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
    """One of the owner's people, or a new login, put to work here. A sales
    manager is made a manager of this business's CRM in the same step."""
    from app.modules.accounts.services import create_member_login
    from app.modules.crm import services as crm
    from app.modules.crm.services import check_email, check_password

    access = _owner_access(db, business_id, user)
    business = access.business
    sales = MemberRole.SALES in body.roles
    if _seats(db, owner=user).free < 1:
        raise NoSeat
    person: User | None = None
    if body.user_id is not None:
        person = db.get(User, body.user_id)
        if person is None or person.crm_owner_id != user.id:
            raise NotYourStaff
    else:
        name, email = body.name.strip(), body.email.strip().lower()
        if not (name and email and body.password):
            raise LoginRequired
    if not sales:
        if person is None:
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
    else:
        # Refuse what the roles and grants cannot be before a manager is made.
        member_services.check(
            db,
            business=business,
            roles=body.roles,
            is_rop=body.is_rop,
            grants=_asked(body.grants),
        )
        viewer = _crm_owner(db, business=business, owner=user)
        if person is None:
            row = crm.add_member(
                db, viewer=viewer, name=name, email=email, password=body.password
            )
        else:
            if any(
                one.user_id == person.id
                for one in members_of(db, business_id=business.id)
            ):
                raise MemberExists
            row = crm.add_person(db, viewer=viewer, user=person)
        member = _mirrored(db, business=business, user_id=row.user_id)
        member_services.change_member(
            db,
            member=member,
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
    replaces what they held; with them, exactly those are kept. Giving the
    sales role makes the person a manager of this business's CRM; taking it
    away takes them off it, and their cards go back to the board."""
    from app.modules.crm import services as crm

    access = _owner_access(db, business_id, user)
    business = access.business
    member = _member(db, business=business, member_id=member_id)
    member_services.check(
        db,
        business=business,
        roles=body.roles,
        is_rop=body.is_rop,
        grants=_asked(body.grants),
    )
    sales = MemberRole.SALES in body.roles
    works = _manager_row(db, business=business, user_id=member.user_id) is not None
    if sales and not works:
        crm.add_person(
            db, viewer=_crm_owner(db, business=business, owner=user), user=member.user
        )
        member = _mirrored(db, business=business, user_id=member.user_id)
    member_services.change_member(
        db,
        member=member,
        roles=body.roles,
        is_rop=body.is_rop,
        grants=_asked(body.grants),
    )
    if works and not sales:
        _leave_crm(db, business=business, owner=user, user_id=member.user_id)
    db.commit()
    return _members(db, business=business, owner=user)


@router.delete("/{business_id}/members/{member_id}", response_model=MembersOut)
def remove_member(
    business_id: uuid.UUID, member_id: uuid.UUID, db: Db, user: CurrentUser
) -> MembersOut:
    """Take the person out of the business, and off its CRM if they were a
    manager there. A login with no other work is closed."""
    access = _owner_access(db, business_id, user)
    business = access.business
    member = _member(db, business=business, member_id=member_id)
    person = member.user_id
    member_services.remove_member(db, member=member)
    _leave_crm(db, business=business, owner=user, user_id=person)
    db.commit()
    return _members(db, business=business, owner=user)


def _network_list(db: Session, *, business: Business) -> NetworksOut:
    return NetworksOut(
        networks=_networks(db, [business.id])[business.id],
        available=[
            AccountChoiceOut(
                id=account.id,
                provider=account.provider,
                external_id=account.external_id,
                name=account.name,
                currency=account.currency,
            )
            for account in network_services.available(db, business=business)
        ],
    )


@router.get("/{business_id}/networks", response_model=NetworksOut)
def list_networks(business_id: uuid.UUID, db: Db, user: CurrentUser) -> NetworksOut:
    """What the business advertises from, and the owner's accounts on other
    networks that may be tied to it."""
    access = _owner_access(db, business_id, user)
    return _network_list(db, business=access.business)


@router.post(
    "/{business_id}/networks",
    response_model=NetworksOut,
    status_code=status.HTTP_201_CREATED,
)
def bind_network(
    business_id: uuid.UUID, body: NetworkIn, db: Db, user: CurrentUser
) -> NetworksOut:
    """Tie one of the owner's accounts on another network to the business.
    Its members get there what they hold on the business's other networks."""
    access = _owner_access(db, business_id, user)
    network_services.bind(db, business=access.business, account_id=body.ad_account_id)
    db.commit()
    return _network_list(db, business=access.business)


@router.delete("/{business_id}/networks/{provider}", response_model=NetworksOut)
def unbind_network(
    business_id: uuid.UUID, provider: str, db: Db, user: CurrentUser
) -> NetworksOut:
    """Untie the business's account on a network. The members' grants over
    that network are taken back; the Meta pair is not untied here."""
    access = _owner_access(db, business_id, user)
    network_services.unbind(db, business=access.business, provider=provider)
    db.commit()
    return _network_list(db, business=access.business)


HISTORY_NAMES = (
    EventName.BUSINESS_MEMBER_ADDED,
    EventName.BUSINESS_MEMBER_CHANGED,
    EventName.BUSINESS_MEMBER_REMOVED,
    EventName.BUSINESS_NETWORK_BOUND,
    EventName.BUSINESS_NETWORK_UNBOUND,
)


def _standing(held: object) -> StandingOut | None:
    if not isinstance(held, dict):
        return None
    return StandingOut(
        roles=list(held.get("roles") or []),
        is_rop=bool(held.get("is_rop")),
        grants=[
            GrantOut(area=area, provider=provider, level=level)
            for area, provider, level in held.get("grants") or []
        ],
    )


def _id(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


@router.get("/{business_id}/history", response_model=HistoryOut)
def history(
    business_id: uuid.UUID, db: Db, user: CurrentUser, limit: int = 100
) -> HistoryOut:
    """Who was added, changed and taken out, and which networks were tied
    and untied, newest first."""
    access = _owner_access(db, business_id, user)
    events = db.scalars(
        select(Event)
        .where(
            Event.owner_id == access.business.user_id,
            Event.aggregate_type == "business",
            Event.aggregate_id == str(business_id),
            Event.name.in_([str(name) for name in HISTORY_NAMES]),
        )
        .order_by(Event.occurred_at.desc(), Event.created_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    items = []
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        about_member = "member_id" in payload
        items.append(
            HistoryItemOut(
                id=event.id,
                at=event.occurred_at,
                kind=event.name.split(".", 1)[-1],
                label=EVENT_NAME_LABELS.get(event.name, event.name),  # type: ignore[call-overload]
                via=str(payload.get("via") or ""),
                member=HistoryPersonOut(
                    member_id=_id(payload.get("member_id")),
                    user_id=_id(payload.get("user_id")),
                    full_name=str(payload.get("full_name") or ""),
                )
                if about_member
                else None,
                before=_standing(payload.get("before")),
                after=_standing(payload.get("after")),
                provider=str(payload.get("provider") or ""),
                account_name=str(payload.get("name") or ""),
            )
        )
    return HistoryOut(items=items)
