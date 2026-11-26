"""The CRM of a business, against PostgreSQL: a sales manager added, changed
and taken out through ``/api/v3/businesses``, one person working the CRM of
two businesses, and what a ROP and a manager with a trimmed grant are let do."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.businesses.models import Business, BusinessMember
from app.modules.businesses.selectors.access import seats_taken
from app.modules.crm.exceptions import NotYours
from app.modules.crm.models import CrmCard, CrmMember, CrmStage
from app.modules.crm.selectors import viewer_for, visible_cards
from app.modules.crm.services import (
    card_for_write,
    change_first_password,
    remove_member,
)
from app.modules.leads.models import Lead
from tests.pg.test_business_links import World
from tests.pg.test_business_members import _business
from tests.pg.test_business_v3 import STRONG, URL, _auth, _new_login, _paid


def _pair_key(world: World, business: Business) -> str:
    return next(
        link.external_id
        for link in world.open_links()
        if link.business_id == business.id
    )


def _rows_of(db: Session, user_id: object) -> list[CrmMember]:
    return list(db.scalars(select(CrmMember).where(CrmMember.user_id == user_id)))


def _add(client: TestClient, world: World, business: Business, body: dict) -> dict:
    made = client.post(
        f"{URL}/{business.id}/members", json=body, headers=_auth(world.owner)
    )
    assert made.status_code == 201, made.text
    return made.json()


def _member(body: dict, email: str) -> dict:
    return next(one for one in body["members"] if one["user"]["email"] == email)


def _card(world: World, business: Business, *, to: object | None, n: int) -> CrmCard:
    db = world.db
    link = next(row for row in world.open_links() if row.business_id == business.id)
    stage = db.scalar(
        select(CrmStage).where(
            CrmStage.page_id == link.page_id, CrmStage.kind == "open"
        )
    )
    if stage is None:
        db.add(
            CrmStage(
                owner_id=world.owner.id,
                page_id=link.page_id,
                ad_account_id=link.ad_account_id,
                name="Yangi",
                color="#000000",
                kind="new",
                position=0,
            )
        )
        stage = CrmStage(
            owner_id=world.owner.id,
            page_id=link.page_id,
            ad_account_id=link.ad_account_id,
            name="Ishda",
            color="#000000",
            kind="open",
            position=1,
        )
        db.add(stage)
        db.flush()
    lead = Lead(
        owner_id=world.owner.id,
        provider="manual",
        leadgen_id=f"manual:{business.id}:{n}",
        full_name=f"Lid {n}",
        phone_e164=f"+99890000{n:04d}",
        submitted_at=world.now,
        received_at=world.now,
    )
    db.add(lead)
    db.flush()
    card = CrmCard(
        owner_id=world.owner.id,
        page_id=link.page_id,
        ad_account_id=link.ad_account_id,
        lead_id=lead.id,
        stage_id=stage.id,
        assignee_id=to,
    )
    db.add(card)
    db.commit()
    return card


def test_a_sales_manager_added_here_is_a_manager_of_the_business_s_crm(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)

    body = _add(client, world, business, _new_login("Vali", ["sales"]))

    member = _member(body, "vali@example.com")
    assert (member["roles"], member["from_crm"]) == (["sales"], True)
    assert {(g["area"], g["provider"], g["level"]) for g in member["grants"]} == {
        ("crm", "meta", "edit"),
        ("crm", "other", "edit"),
    }
    vali = db.get(User, member["user"]["id"])
    assert vali is not None
    (row,) = _rows_of(db, vali.id)
    assert (row.business_id, row.is_active, row.must_change_password) == (
        business.id,
        True,
        True,
    )
    viewer = viewer_for(db, user=vali)
    assert viewer.pair is not None and viewer.pair.key == _pair_key(world, business)
    assert viewer.may_work and not viewer.reads_all and not viewer.read_only


def test_one_person_works_the_crm_of_two_businesses(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)
    body = _add(client, world, first, _new_login("Vali", ["sales"]))
    person = _member(body, "vali@example.com")["user"]

    _add(client, world, second, {"user_id": person["id"], "roles": ["sales"]})

    vali = db.get(User, person["id"])
    assert vali is not None
    rows = _rows_of(db, vali.id)
    assert {row.business_id for row in rows} == {first.id, second.id}
    # The second row asks for no new password: the person has one already.
    assert sorted(row.must_change_password for row in rows) == [False, True]
    assert seats_taken(db, owner_id=world.owner.id) == 2

    here = viewer_for(db, user=vali, wanted=_pair_key(world, second))
    there = viewer_for(db, user=vali, wanted=_pair_key(world, first))
    unnamed = viewer_for(db, user=vali)
    assert here.pair is not None and here.pair.key == "p2:act_2"
    assert there.pair is not None and there.pair.key == "p1:act_1"
    assert unnamed.pair is not None and unnamed.pair.key == "p1:act_1"
    assert here.member is not None and here.member.business_id == second.id

    change_first_password(db, user=vali, password=STRONG, again=STRONG)
    db.commit()
    assert [row.must_change_password for row in _rows_of(db, vali.id)] == [
        False,
        False,
    ]

    twice = client.post(
        f"{URL}/{second.id}/members",
        json={"user_id": person["id"], "roles": ["sales"]},
        headers=_auth(world.owner),
    )
    assert twice.status_code == 409


def test_each_business_hands_its_own_leads_to_its_own_managers(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)
    body = _add(client, world, first, _new_login("Vali", ["sales"]))
    person = _member(body, "vali@example.com")["user"]
    _add(client, world, second, {"user_id": person["id"], "roles": ["sales"]})
    vali = db.get(User, person["id"])
    assert vali is not None
    mine = _card(world, first, to=vali.id, n=1)
    other = _card(world, second, to=vali.id, n=2)

    def seen(pair: str) -> set[object]:
        viewer = viewer_for(db, user=vali, wanted=pair)
        return set(db.scalars(visible_cards(viewer).with_only_columns(CrmCard.id)))

    assert seen("p1:act_1") == {mine.id}
    assert seen("p2:act_2") == {other.id}


def test_a_rop_reads_every_card_and_changes_only_their_own(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)
    # A second page gives the plan a second free seat.
    _business(world, "p2", "act_2")
    body = _add(client, world, business, _new_login("Vali", ["sales"]))
    body = _add(client, world, business, _new_login("Gulnora", ["sales"], is_rop=True))
    vali = db.get(User, _member(body, "vali@example.com")["user"]["id"])
    rop = db.get(User, _member(body, "gulnora@example.com")["user"]["id"])
    assert vali is not None and rop is not None
    of_vali = _card(world, business, to=vali.id, n=1)
    of_rop = _card(world, business, to=rop.id, n=2)

    manager, head = viewer_for(db, user=vali), viewer_for(db, user=rop)

    assert (manager.reads_all, head.reads_all) == (False, True)
    ids = CrmCard.id
    assert set(db.scalars(visible_cards(manager).with_only_columns(ids))) == {
        of_vali.id
    }
    assert set(db.scalars(visible_cards(head).with_only_columns(ids))) == {
        of_vali.id,
        of_rop.id,
    }
    assert card_for_write(db, viewer=head, card_id=str(of_rop.id)).id == of_rop.id
    with pytest.raises(NotYours):
        card_for_write(db, viewer=head, card_id=str(of_vali.id))


def test_a_trimmed_crm_grant_makes_the_board_read_only_or_shuts_it(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)
    owner = _auth(world.owner)
    body = _add(client, world, business, _new_login("Vali", ["sales"]))
    member = _member(body, "vali@example.com")
    vali = db.get(User, member["user"]["id"])
    assert vali is not None
    card = _card(world, business, to=vali.id, n=1)
    url = f"{URL}/{business.id}/members/{member['id']}"

    def grant(*grants: dict[str, str]) -> None:
        answer = client.patch(
            url, json={"roles": ["sales"], "grants": list(grants)}, headers=owner
        )
        assert answer.status_code == 200, answer.text
        db.expire_all()

    grant({"area": "crm", "provider": "meta", "level": "view"})
    viewer = viewer_for(db, user=vali)
    assert viewer.read_only and viewer.may_work
    assert set(db.scalars(visible_cards(viewer).with_only_columns(CrmCard.id))) == {
        card.id
    }
    with pytest.raises(NotYours):
        card_for_write(db, viewer=viewer, card_id=str(card.id))

    grant({"area": "crm", "provider": "other", "level": "edit"})
    shut = viewer_for(db, user=vali)
    assert shut.barred and not shut.may_work

    grant({"area": "crm", "provider": "meta", "level": "edit"})
    back = viewer_for(db, user=vali)
    assert back.may_work and not back.read_only and not back.barred
    assert card_for_write(db, viewer=back, card_id=str(card.id)).id == card.id


def test_the_sales_role_taken_away_takes_the_person_off_the_crm(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)
    owner = _auth(world.owner)
    body = _add(client, world, business, _new_login("Vali", ["sales", "targetolog"]))
    member = _member(body, "vali@example.com")
    assert member["roles"] == ["sales", "targetolog"]
    vali = db.get(User, member["user"]["id"])
    assert vali is not None
    card = _card(world, business, to=vali.id, n=1)

    changed = client.patch(
        f"{URL}/{business.id}/members/{member['id']}",
        json={"roles": ["targetolog"]},
        headers=owner,
    )

    assert changed.status_code == 200, changed.text
    (after,) = changed.json()["members"]
    assert (after["roles"], after["from_crm"]) == (["targetolog"], False)
    assert after["grants"] == [{"area": "ads", "provider": "meta", "level": "edit"}]
    db.expire_all()
    assert _rows_of(db, vali.id) == []
    assert db.get(User, vali.id) is not None
    db.refresh(card)
    assert card.assignee_id is None

    # And given back, the same person is a manager again.
    again = client.patch(
        f"{URL}/{business.id}/members/{member['id']}",
        json={"roles": ["sales", "targetolog"], "is_rop": True},
        headers=owner,
    )
    assert again.status_code == 200, again.text
    (after,) = again.json()["members"]
    assert (after["roles"], after["from_crm"], after["is_rop"]) == (
        ["sales", "targetolog"],
        True,
        True,
    )
    assert len(_rows_of(db, vali.id)) == 1


def test_a_sales_manager_taken_out_leaves_the_crm_and_their_login_is_closed(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)
    body = _add(client, world, business, _new_login("Vali", ["sales"]))
    member = _member(body, "vali@example.com")
    user_id = member["user"]["id"]

    gone = client.delete(
        f"{URL}/{business.id}/members/{member['id']}", headers=_auth(world.owner)
    )

    assert gone.status_code == 200, gone.text
    assert gone.json()["members"] == []
    assert gone.json()["seats"]["taken"] == 0
    db.expire_all()
    assert db.get(User, user_id) is None
    assert _rows_of(db, user_id) == []
    assert db.scalars(select(BusinessMember)).all() == []


def test_a_person_taken_out_of_one_business_keeps_working_the_other(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)
    owner = _auth(world.owner)
    body = _add(client, world, first, _new_login("Vali", ["sales"]))
    person = _member(body, "vali@example.com")
    _add(client, world, second, {"user_id": person["user"]["id"], "roles": ["sales"]})
    here = _card(world, first, to=person["user"]["id"], n=1)
    there = _card(world, second, to=person["user"]["id"], n=2)

    gone = client.delete(f"{URL}/{first.id}/members/{person['id']}", headers=owner)

    assert gone.status_code == 200, gone.text
    assert gone.json()["members"] == []
    db.expire_all()
    # Only the cards of the business they left go back to its board.
    assert (here.assignee_id, str(there.assignee_id)) == (None, person["user"]["id"])
    vali = db.get(User, person["user"]["id"])
    assert vali is not None and vali.is_active
    (row,) = _rows_of(db, vali.id)
    assert row.business_id == second.id
    left = client.get(f"{URL}/{second.id}/members", headers=owner).json()
    assert [one["user"]["email"] for one in left["members"]] == ["vali@example.com"]
    mine = client.get(URL, headers=_auth(vali)).json()["businesses"]
    assert [card["id"] for card in mine] == [str(second.id)]


def test_the_crm_s_own_removal_keeps_a_login_that_works_elsewhere(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)
    body = _add(client, world, first, _new_login("Vali", ["sales"]))
    person = _member(body, "vali@example.com")["user"]
    _add(client, world, second, {"user_id": person["id"], "roles": ["sales"]})
    vali = db.get(User, person["id"])
    assert vali is not None
    row = next(one for one in _rows_of(db, vali.id) if one.business_id == first.id)

    viewer = viewer_for(db, user=world.owner, wanted=_pair_key(world, first))
    remove_member(db, viewer=viewer, member_id=str(row.id))
    db.commit()

    db.expire_all()
    assert db.get(User, vali.id) is not None
    assert [one.business_id for one in _rows_of(db, vali.id)] == [second.id]
    members = {
        one.business_id: one.is_active
        for one in db.scalars(
            select(BusinessMember).where(BusinessMember.user_id == vali.id)
        )
    }
    assert members == {first.id: False, second.id: True}

    # The last pair gone, the login goes too, as it always did.
    last = _rows_of(db, vali.id)[0]
    viewer = viewer_for(db, user=world.owner, wanted=_pair_key(world, second))
    remove_member(db, viewer=viewer, member_id=str(last.id))
    db.commit()
    db.expire_all()
    assert db.get(User, vali.id) is None
