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
from app.modules.crm.exceptions import MemberLacksSource, NotYours, UnknownCard
from app.modules.crm.models import CrmCard, CrmMember, CrmSetup, CrmStage
from app.modules.crm.selectors import viewer_for, visible_cards
from app.modules.crm.services import (
    add_manual,
    assign_card,
    card_for_write,
    change_first_password,
    place_lead,
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


@pytest.fixture
def seated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every manager in a seat. The plan's free seat is one a page, and the
    seats bought are another matter with tests of its own."""
    from app.modules.crm import selectors, services

    def everyone(db: Session, *, owner: User, at: object) -> frozenset[object]:
        return frozenset(
            db.scalars(
                select(CrmMember.id).where(
                    CrmMember.owner_id == owner.id, CrmMember.is_active.is_(True)
                )
            )
        )

    monkeypatch.setattr(selectors, "seated_ids", everyone)
    monkeypatch.setattr(services, "seated_ids", everyone)


def _running(db: Session, link: object) -> None:
    """The pair's board switched on, as the owner's last setup step does."""
    setup = db.scalar(
        select(CrmSetup).where(
            CrmSetup.page_id == link.page_id,  # type: ignore[attr-defined]
            CrmSetup.ad_account_id == link.ad_account_id,  # type: ignore[attr-defined]
        )
    )
    if setup is None:
        setup = CrmSetup(
            owner_id=link.owner_id,  # type: ignore[attr-defined]
            page_id=link.page_id,  # type: ignore[attr-defined]
            ad_account_id=link.ad_account_id,  # type: ignore[attr-defined]
            currency="USD",
        )
        db.add(setup)
    setup.state, setup.step = "on", 5
    db.flush()


def _card(
    world: World,
    business: Business,
    *,
    to: object | None,
    n: int,
    provider: str = "manual",
) -> CrmCard:
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
        provider=provider,
        leadgen_id=f"{provider}:{business.id}:{n}",
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


def test_a_crm_grant_is_held_per_source_of_the_lead(
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
    advert = _card(world, business, to=vali.id, n=1, provider="meta")
    typed = _card(world, business, to=vali.id, n=2)
    url = f"{URL}/{business.id}/members/{member['id']}"

    def grant(*grants: dict[str, str]):  # type: ignore[no-untyped-def]
        answer = client.patch(
            url, json={"roles": ["sales"], "grants": list(grants)}, headers=owner
        )
        assert answer.status_code == 200, answer.text
        db.expire_all()
        return viewer_for(db, user=vali)

    def seen(viewer) -> set[object]:  # type: ignore[no-untyped-def]
        return set(db.scalars(visible_cards(viewer).with_only_columns(CrmCard.id)))

    # The ready set: every source, to change.
    full = viewer_for(db, user=vali)
    assert full.sources is None and seen(full) == {advert.id, typed.id}

    # Meta to read alone: the advert's lead is shown and not changed, and a
    # customer typed in is not there at all.
    reading = grant({"area": "crm", "provider": "meta", "level": "view"})
    assert reading.read_only and reading.may_work
    assert seen(reading) == {advert.id}
    with pytest.raises(NotYours):
        card_for_write(db, viewer=reading, card_id=str(advert.id))

    # «Boshqa manba» alone: the board opens on the typed customers only.
    typed_only = grant({"area": "crm", "provider": "other", "level": "edit"})
    assert typed_only.may_work and not typed_only.read_only
    assert seen(typed_only) == {typed.id}
    assert card_for_write(db, viewer=typed_only, card_id=str(typed.id)).id == typed.id
    with pytest.raises(UnknownCard):
        card_for_write(db, viewer=typed_only, card_id=str(advert.id))

    # Both, one to read and one to change: each card by its own source.
    mixed = grant(
        {"area": "crm", "provider": "meta", "level": "view"},
        {"area": "crm", "provider": "other", "level": "edit"},
    )
    assert not mixed.read_only and seen(mixed) == {advert.id, typed.id}
    assert card_for_write(db, viewer=mixed, card_id=str(typed.id)).id == typed.id
    with pytest.raises(NotYours):
        card_for_write(db, viewer=mixed, card_id=str(advert.id))

    # With no CRM grant left the board is shut.
    shut = grant()
    assert shut.barred and not shut.may_work

    back = grant(
        {"area": "crm", "provider": "meta", "level": "edit"},
        {"area": "crm", "provider": "other", "level": "edit"},
    )
    assert back.may_work and not back.read_only and not back.barred
    assert card_for_write(db, viewer=back, card_id=str(advert.id)).id == advert.id


def test_a_customer_is_typed_in_only_with_the_grant_over_other_sources(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)
    body = _add(
        client,
        world,
        business,
        _new_login(
            "Vali",
            ["sales"],
            grants=[{"area": "crm", "provider": "meta", "level": "edit"}],
        ),
    )
    vali = db.get(User, _member(body, "vali@example.com")["user"]["id"])
    assert vali is not None
    _card(world, business, to=None, n=1)
    link = next(row for row in world.open_links() if row.business_id == business.id)
    _running(db, link)
    db.commit()

    with pytest.raises(NotYours):
        add_manual(
            db, viewer=viewer_for(db, user=vali), name="Mijoz", phone="+998901112233"
        )


def test_a_rop_hands_cards_to_the_managers_and_a_manager_does_not(
    client: TestClient, db: Session, seated: None
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)
    _business(world, "p2", "act_2")
    _business(world, "p3", "act_3")
    body = _add(client, world, business, _new_login("Vali", ["sales"]))
    body = _add(
        client,
        world,
        business,
        _new_login(
            "Sardor",
            ["sales"],
            grants=[{"area": "crm", "provider": "other", "level": "edit"}],
        ),
    )
    body = _add(client, world, business, _new_login("Gulnora", ["sales"], is_rop=True))
    vali, sardor, rop = (
        db.get(User, _member(body, f"{name}@example.com")["user"]["id"])
        for name in ("vali", "sardor", "gulnora")
    )
    assert vali is not None and sardor is not None and rop is not None
    card = _card(world, business, to=vali.id, n=1, provider="meta")
    head, manager = viewer_for(db, user=rop), viewer_for(db, user=vali)
    assert (head.may_assign, manager.may_assign) == (True, False)

    with pytest.raises(NotYours):
        assign_card(db, viewer=manager, card_id=str(card.id), user_id=str(rop.id))

    moved = assign_card(db, viewer=head, card_id=str(card.id), user_id=str(rop.id))
    assert moved.assignee_id == rop.id
    back = assign_card(db, viewer=head, card_id=str(card.id), user_id=str(vali.id))
    assert back.assignee_id == vali.id
    # Not to a manager who holds nothing over the lead's source,
    with pytest.raises(MemberLacksSource):
        assign_card(db, viewer=head, card_id=str(card.id), user_id=str(sardor.id))
    # and not to the owner: that is the owner's own to do.
    with pytest.raises(NotYours):
        assign_card(db, viewer=head, card_id=str(card.id), user_id=str(world.owner.id))
    freed = assign_card(db, viewer=head, card_id=str(card.id), user_id="")
    assert freed.assignee_id is None
    # The board running, and the managers past their first password.
    link = next(row for row in world.open_links() if row.business_id == business.id)
    _running(db, link)
    for row in db.scalars(select(CrmMember)):
        row.must_change_password = False
    db.commit()

    # Over the wire: the board says who may hand out, and the route obeys.
    board = client.get("/api/v1/crm", headers=_auth(rop))
    assert board.status_code == 200, board.text
    assert board.json()["may_assign"] is True
    done = client.post(
        f"/api/v1/crm/cards/{card.id}/assign",
        json={"assignee": str(vali.id)},
        headers=_auth(rop),
    )
    assert done.status_code == 200, done.text
    refused = client.post(
        f"/api/v1/crm/cards/{card.id}/assign",
        json={"assignee": str(rop.id)},
        headers=_auth(vali),
    )
    assert refused.status_code == 404


def test_a_lead_of_another_network_lands_on_the_business_s_board(
    client: TestClient, db: Session, seated: None
) -> None:
    from tests.pg.test_business_networks import _bind, _google

    world = World(db)
    business = _business(world)
    _paid(world)
    _business(world, "p2", "act_2")
    account = _google(world, "111")
    db.commit()
    # Vali holds Meta and the typed customers; Gulnora is added after Google
    # is tied on, and holds every source.
    body = _add(client, world, business, _new_login("Vali", ["sales"]))
    assert _bind(client, world.owner, business, account).status_code == 201
    vali_row = _member(body, "vali@example.com")
    trimmed = client.patch(
        f"{URL}/{business.id}/members/{vali_row['id']}",
        json={
            "roles": ["sales"],
            "grants": [
                {"area": "crm", "provider": "meta", "level": "edit"},
                {"area": "crm", "provider": "other", "level": "edit"},
            ],
        },
        headers=_auth(world.owner),
    )
    assert trimmed.status_code == 200, trimmed.text
    body = _add(client, world, business, _new_login("Gulnora", ["sales"]))
    vali = db.get(User, vali_row["user"]["id"])
    gulnora = db.get(User, _member(body, "gulnora@example.com")["user"]["id"])
    assert vali is not None and gulnora is not None
    _card(world, business, to=None, n=1)  # makes the board's columns
    link = next(row for row in world.open_links() if row.business_id == business.id)
    _running(db, link)
    leads = []
    for n in (1, 2):
        lead = Lead(
            owner_id=world.owner.id,
            provider="google",
            leadgen_id=f"g{n}",
            full_name=f"Google lid {n}",
            phone_e164=f"+99890111000{n}",
            campaign_external_id="customers/111/campaigns/5",
            submitted_at=world.now,
            received_at=world.now,
        )
        db.add(lead)
        leads.append(lead)
    stranger = Lead(
        owner_id=world.owner.id,
        provider="google",
        leadgen_id="g9",
        campaign_external_id="customers/999/campaigns/5",
        submitted_at=world.now,
        received_at=world.now,
    )
    db.add(stranger)
    db.commit()

    assert [place_lead(db, lead_id=str(lead.id)) for lead in leads] == [
        "placed",
        "placed",
    ]
    # An account tied to no business brings nothing to any board.
    assert place_lead(db, lead_id=str(stranger.id)) == "skipped"

    cards = list(
        db.scalars(
            select(CrmCard).where(CrmCard.lead_id.in_([lead.id for lead in leads]))
        )
    )
    assert {card.business_id for card in cards} == {business.id}
    # Handed only to the manager who may work Google's leads.
    assert {card.assignee_id for card in cards} == {gulnora.id}
    seen = set(
        db.scalars(
            visible_cards(viewer_for(db, user=vali)).with_only_columns(CrmCard.id)
        )
    )
    assert not seen & {card.id for card in cards}


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
