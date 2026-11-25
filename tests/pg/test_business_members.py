"""The people of a business, against PostgreSQL: the grants a role starts
with, what the owner, a member and a stranger may do, and the membership
kept level with a CRM manager the cabinet added."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.businesses.exceptions import (
    BadGrant,
    MemberExists,
    NoAccess,
    NotYourStaff,
    OwnerIsNotMember,
    RoleRequired,
    RopNeedsSales,
    UnknownBusiness,
    UnknownRole,
)
from app.modules.businesses.models import Business, BusinessMember
from app.modules.businesses.selectors.access import (
    access_for,
    businesses_of,
    members_of,
    seats_taken,
)
from app.modules.businesses.services.members import (
    add_member,
    change_member,
    preset,
    remove_member,
)
from app.modules.crm.models import CrmMember
from tests.pg.test_business_links import World

ADS_META, CRM_META, CRM_OTHER = ("ads", "meta"), ("crm", "meta"), ("crm", "other")


def _staff(world: World, name: str, *, of: User | None = None) -> User:
    user = User(
        email=f"{name}@example.com",
        full_name=name,
        password="!",
        date_joined=world.now,
        crm_owner_id=(of or world.owner).id,
    )
    world.db.add(user)
    world.db.flush()
    return user


def _business(world: World, page_id: str = "p1", account_id: str = "act_1") -> Business:
    page = world.page(page_id)
    world.pair(page, world.account(account_id))
    world.db.commit()
    (link,) = [row for row in world.open_links() if row.page_id == page.id]
    business = world.db.get(Business, link.business_id)
    assert business is not None
    return business


def _grants(member: BusinessMember) -> dict[tuple[str, str], str]:
    return {(grant.area, grant.provider): grant.level for grant in member.grants}


def test_what_each_role_starts_with() -> None:
    assert preset(roles=["targetolog"], networks=["meta"]) == {ADS_META: "edit"}
    assert preset(roles=["sales"], networks=["meta"]) == {
        CRM_META: "edit",
        CRM_OTHER: "edit",
    }
    assert preset(roles=["sales", "targetolog"], networks=["google", "meta"]) == {
        ("ads", "google"): "edit",
        ADS_META: "edit",
        ("crm", "google"): "edit",
        CRM_META: "edit",
        CRM_OTHER: "edit",
    }
    assert preset(roles=["targetolog"], networks=[]) == {}


def test_a_targetolog_changes_adverts_and_does_not_see_the_crm(db: Session) -> None:
    world = World(db)
    business = _business(world)
    ali = _staff(world, "ali")

    member = add_member(db, business=business, user=ali, roles=["targetolog"])
    db.commit()

    assert _grants(member) == {ADS_META: "edit"}
    access = access_for(db, business_id=business.id, user=ali)
    assert not access.is_owner
    assert access.may("ads", "meta", "edit") and access.may("ads", "meta", "view")
    assert not access.may("crm", "meta") and not access.may("crm", "other")
    assert not access.may("ads", "google")
    assert access.reaches("ads") and not access.reaches("crm")
    assert not access.reads_all_leads
    with pytest.raises(NoAccess):
        access.require("crm", "meta")
    with pytest.raises(NoAccess):
        access.require_owner()


def test_a_sales_manager_reads_their_own_leads_and_a_rop_everybody_s(
    db: Session,
) -> None:
    world = World(db)
    business = _business(world)
    vali, gulnora = _staff(world, "vali"), _staff(world, "gulnora")

    add_member(db, business=business, user=vali, roles=["sales"])
    add_member(db, business=business, user=gulnora, roles=["sales"], is_rop=True)
    db.commit()

    manager = access_for(db, business_id=business.id, user=vali)
    rop = access_for(db, business_id=business.id, user=gulnora)
    assert manager.networks("crm", "edit") == {"meta", "other"}
    assert not manager.may("ads", "meta")
    assert (manager.reads_all_leads, rop.reads_all_leads) == (False, True)
    assert rop.is_rop and not manager.is_rop


def test_one_person_may_hold_both_roles_and_the_owner_may_trim_them(
    db: Session,
) -> None:
    world = World(db)
    business = _business(world)
    ali = _staff(world, "ali")
    member = add_member(db, business=business, user=ali, roles=["sales", "targetolog"])
    assert _grants(member) == {ADS_META: "edit", CRM_META: "edit", CRM_OTHER: "edit"}

    change_member(
        db,
        member=member,
        roles=["sales", "targetolog"],
        is_rop=False,
        grants={ADS_META: "view", CRM_META: "edit"},
    )
    db.commit()

    access = access_for(db, business_id=business.id, user=ali)
    assert access.may("ads", "meta", "view") and not access.may("ads", "meta", "edit")
    assert access.may("crm", "meta", "edit") and not access.may("crm", "other")
    assert seats_taken(db, owner_id=world.owner.id) == 1

    # Picking the roles again with no grants named puts the ready set back.
    change_member(db, member=member, roles=["targetolog"], is_rop=False)
    assert _grants(member) == {ADS_META: "edit"}


def test_the_owner_may_do_everything_and_a_stranger_is_told_nothing(
    db: Session,
) -> None:
    world, other = World(db), World(db, "boshqa@example.com")
    business = _business(world)
    stranger = _staff(other, "begona")

    owner = access_for(db, business_id=business.id, user=world.owner)
    assert owner.is_owner and owner.reads_all_leads
    assert owner.may("ads", "google", "edit") and owner.may("crm", "other", "edit")
    owner.require_owner()

    for nobody in (stranger, other.owner):
        with pytest.raises(UnknownBusiness):
            access_for(db, business_id=business.id, user=nobody)


def test_who_may_not_be_added_and_what_may_not_be_granted(db: Session) -> None:
    world, other = World(db), World(db, "boshqa@example.com")
    business = _business(world)
    ali = _staff(world, "ali")

    with pytest.raises(OwnerIsNotMember):
        add_member(db, business=business, user=world.owner, roles=["sales"])
    with pytest.raises(NotYourStaff):
        add_member(db, business=business, user=_staff(other, "begona"), roles=["sales"])
    with pytest.raises(RoleRequired):
        add_member(db, business=business, user=ali, roles=[])
    with pytest.raises(UnknownRole):
        add_member(db, business=business, user=ali, roles=["admin"])
    with pytest.raises(RopNeedsSales):
        add_member(db, business=business, user=ali, roles=["targetolog"], is_rop=True)
    for bad in (
        {("ads", "google"): "edit"},
        {("ads", "other"): "view"},
        {("billing", "meta"): "view"},
        {("crm", "meta"): "owner"},
    ):
        with pytest.raises(BadGrant):
            add_member(db, business=business, user=ali, roles=["sales"], grants=bad)
    assert members_of(db, business_id=business.id) == []

    add_member(db, business=business, user=ali, roles=["sales"])
    with pytest.raises(MemberExists):
        add_member(db, business=business, user=ali, roles=["targetolog"])


def test_a_removed_member_loses_the_business_and_comes_back_on_the_same_row(
    db: Session,
) -> None:
    world = World(db)
    business = _business(world)
    ali = _staff(world, "ali")
    member = add_member(db, business=business, user=ali, roles=["sales"])
    db.commit()

    remove_member(db, member=member)
    db.commit()

    with pytest.raises(UnknownBusiness):
        access_for(db, business_id=business.id, user=ali)
    assert members_of(db, business_id=business.id) == []
    assert seats_taken(db, owner_id=world.owner.id) == 0
    assert businesses_of(db, user=ali) == []

    again = add_member(db, business=business, user=ali, roles=["targetolog"])
    db.commit()
    assert again.id == member.id and again.removed_at is None
    assert _grants(again) == {ADS_META: "edit"}


def test_a_person_in_two_businesses_takes_two_seats_and_switches_between_them(
    db: Session,
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    ali = _staff(world, "ali")
    add_member(db, business=first, user=ali, roles=["targetolog"])
    add_member(db, business=second, user=ali, roles=["sales"])
    db.commit()

    assert {row.id for row in businesses_of(db, user=ali)} == {first.id, second.id}
    assert {row.id for row in businesses_of(db, user=world.owner)} == {
        first.id,
        second.id,
    }
    assert seats_taken(db, owner_id=world.owner.id) == 2
    assert access_for(db, business_id=first.id, user=ali).may("ads", "meta", "edit")
    assert not access_for(db, business_id=second.id, user=ali).may("ads", "meta")


def _manager(world: World, business: Business, name: str) -> CrmMember:
    link = next(row for row in world.open_links() if row.business_id == business.id)
    row = CrmMember(
        owner_id=world.owner.id,
        page_id=link.page_id,
        ad_account_id=link.ad_account_id,
        user_id=_staff(world, name).id,
        must_change_password=False,
    )
    world.db.add(row)
    world.db.commit()
    return row


def _mirrored(db: Session, manager: CrmMember) -> BusinessMember:
    return db.scalars(
        select(BusinessMember).where(BusinessMember.crm_member_id == manager.id)
    ).one()


def test_a_manager_the_cabinet_adds_becomes_a_sales_member(db: Session) -> None:
    world = World(db)
    business = _business(world)

    manager = _manager(world, business, "vali")

    member = _mirrored(db, manager)
    assert (member.business_id, member.user_id) == (business.id, manager.user_id)
    assert (member.roles, member.is_rop, member.is_active) == (["sales"], False, True)
    assert _grants(member) == {CRM_META: "edit", CRM_OTHER: "edit"}


def test_a_manager_switched_off_and_on_takes_the_membership_along(
    db: Session,
) -> None:
    world = World(db)
    manager = _manager(world, _business(world), "vali")

    manager.is_active = False
    db.commit()
    member = _mirrored(db, manager)
    assert not member.is_active and member.removed_at is not None

    manager.is_active = True
    db.commit()
    db.refresh(member)
    assert member.is_active and member.removed_at is None


def test_a_manager_moved_to_another_pair_moves_to_its_business(db: Session) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    manager = _manager(world, first, "vali")
    old = _mirrored(db, manager)
    there = next(row for row in world.open_links() if row.business_id == second.id)

    manager.page_id, manager.ad_account_id = there.page_id, there.ad_account_id
    db.commit()

    assert manager.business_id == second.id
    db.refresh(old)
    assert (old.is_active, old.crm_member_id) == (False, None)
    assert _mirrored(db, manager).business_id == second.id
    assert seats_taken(db, owner_id=world.owner.id) == 1


def test_a_role_the_owner_added_to_a_manager_is_kept(db: Session) -> None:
    world = World(db)
    manager = _manager(world, _business(world), "vali")
    member = _mirrored(db, manager)
    change_member(db, member=member, roles=["sales", "targetolog"], is_rop=True)
    db.commit()

    manager.takes_leads = False
    db.commit()

    db.refresh(member)
    assert (member.roles, member.is_rop) == (["sales", "targetolog"], True)
    assert _grants(member) == {ADS_META: "edit", CRM_META: "edit", CRM_OTHER: "edit"}
