"""What is known about a business, against PostgreSQL: the narrower kinds
nobody makes twice, what the office advises a direction, the knowledge
changed in small steps by two chats at once, and the routes over all of it."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.constants import EventName
from app.modules.audit.models import Event
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.businesses.constants import (
    MAX_ITEMS,
    MAX_PENDING,
    KnowledgeSource,
    SubtypeOrigin,
    TypeState,
)
from app.modules.businesses.exceptions import (
    BadAdvice,
    BadKnowledgeChange,
    BadSubtype,
    KnowledgeFull,
    KnowledgeMoved,
    SubtypeNameTaken,
    UnknownItem,
    UnknownProposal,
)
from app.modules.businesses.models import (
    Business,
    BusinessCategory,
    BusinessKnowledge,
    BusinessSubtype,
)
from app.modules.businesses.selectors.knowledge import brief, known
from app.modules.businesses.services import advice, kinds, knowledge, subtypes
from app.modules.businesses.services.members import add_member
from tests.pg.test_business_links import World
from tests.pg.test_business_members import _business, _staff
from tests.pg.test_business_v3 import URL, _auth
from tests.pg.test_office_actions import _staff as _office

OFFICE = "/api/v1/office"


def _direction(
    db: Session, key: str = "furniture", label: str = "Mebel"
) -> BusinessCategory:
    row = BusinessCategory(key=key, label_uz=label, preset_key=key)
    db.add(row)
    db.flush()
    return row


def _items(db: Session, business: Business) -> dict[str, dict[str, object]]:
    return {str(item["name"]): item for item in known(db, business).items}


# -- the narrower kinds ------------------------------------------------------


def test_a_name_is_levelled_before_it_is_compared() -> None:
    assert subtypes.level("  Oshxona   MEBELI! ") == "oshxona mebeli"
    assert subtypes.level("Go‘zallik saloni") == subtypes.level("go'zallik saloni")
    assert subtypes.level("Кухонная мебель") == "кухонная мебель"
    assert subtypes.level("?!") == ""


def test_the_same_kind_is_never_made_twice(db: Session) -> None:
    mebel = _direction(db)
    first, made = subtypes.ensure(
        db,
        direction=mebel,
        name="Oshxona mebeli",
        synonyms=["kuxnya", "Kuxnya", "oshxona mebeli"],
    )
    again, made_again = subtypes.ensure(db, direction=mebel, name=" oshxona  MEBELI ")
    by_word, made_by_word = subtypes.ensure(db, direction=mebel, name="Kuxnya")

    assert (made, made_again, made_by_word) == (True, False, False)
    assert first.id == again.id == by_word.id
    assert first.synonyms == ["kuxnya"]
    assert (first.origin, first.is_checked) == ("ai", False)
    assert db.query(BusinessSubtype).count() == 1


def test_the_same_name_under_another_direction_is_another_kind(db: Session) -> None:
    mebel, services = _direction(db), _direction(db, "services", "Xizmatlar")
    one, _ = subtypes.ensure(db, direction=mebel, name="Ta'mirlash")
    two, made = subtypes.ensure(
        db, direction=services, name="Ta'mirlash", origin=SubtypeOrigin.STAFF
    )

    assert made and one.id != two.id
    assert two.is_checked is True


def test_a_kind_needs_a_name(db: Session) -> None:
    mebel = _direction(db)
    for bad in ("", "   ", "?!", "x" * 81):
        with pytest.raises(BadSubtype):
            subtypes.ensure(db, direction=mebel, name=bad)


def test_two_kinds_that_are_one_are_merged(db: Session) -> None:
    world = World(db)
    business = _business(world)
    mebel = _direction(db)
    kept, _ = subtypes.ensure(db, direction=mebel, name="Oshxona mebeli")
    given_up, _ = subtypes.ensure(
        db, direction=mebel, name="Kuxnya mebel", synonyms=["kuxnya"]
    )
    kinds.set_kind(db, business=business, direction=mebel, subtype=given_up)
    db.commit()

    result = subtypes.merge(db, source=given_up, target=kept)
    db.commit()

    assert result.id == kept.id
    assert kept.synonyms == ["Kuxnya mebel", "kuxnya"]
    assert (given_up.merged_into_id, given_up.is_active) == (kept.id, False)
    assert known(db, business).subtype.id == kept.id
    # The name given up now finds the kind kept, and makes nothing.
    found, made = subtypes.ensure(db, direction=mebel, name="kuxnya mebel")
    assert (found.id, made) == (kept.id, False)
    with pytest.raises(BadSubtype):
        subtypes.merge(db, source=kept, target=kept)
    with pytest.raises(BadSubtype):
        subtypes.merge(db, source=given_up, target=kept)


def test_kinds_of_two_directions_are_not_merged(db: Session) -> None:
    mebel, services = _direction(db), _direction(db, "services", "Xizmatlar")
    one, _ = subtypes.ensure(db, direction=mebel, name="Mebel ta'miri")
    two, _ = subtypes.ensure(db, direction=services, name="Ta'mirlash")

    with pytest.raises(BadSubtype):
        subtypes.merge(db, source=one, target=two)


def test_a_rename_cannot_take_another_kind_s_name(db: Session) -> None:
    mebel = _direction(db)
    one, _ = subtypes.ensure(db, direction=mebel, name="Oshxona mebeli")
    two, _ = subtypes.ensure(db, direction=mebel, name="Ofis mebeli")

    with pytest.raises(SubtypeNameTaken):
        subtypes.change(db, subtype=two, name="oshxona MEBELI")
    subtypes.change(
        db,
        subtype=two,
        name="Ofis uchun mebel",
        synonyms=["ofis mebeli"],
        is_checked=True,
    )
    assert (two.name_key, two.synonyms, two.is_checked) == (
        "ofis uchun mebel",
        ["ofis mebeli"],
        True,
    )
    assert one.name == "Oshxona mebeli"


# -- what the office advises -------------------------------------------------


def test_a_direction_is_advised_two_goals(db: Session) -> None:
    services = _direction(db, "services", "Xizmatlar")
    assert advice.advice_of(db, direction=services) is None
    assert "telegram" in advice.runnable(services)

    advice.save_rule(
        db,
        direction=services,
        goal_first="leads",
        reason_first="  Narx ishni ko'rgandan   keyin aytiladi. ",
        goal_second="messages",
        when_second="Narx oldindan aniq bo'lsa.",
        never_say="Natijani kafolatlash.",
    )
    held = advice.advice_of(db, direction=services)

    assert held is not None
    assert held.goals == ("leads", "messages")
    assert held.reason_first == "Narx ishni ko'rgandan keyin aytiladi."
    assert advice.run_as("telegram") == "traffic"
    # Written again, it replaces what was there.
    advice.save_rule(
        db, direction=services, goal_first="messages", reason_first="Tez javob."
    )
    again = advice.advice_of(db, direction=services)
    assert again is not None and again.goals == ("messages",)
    assert again.when_second == ""


def test_advice_that_cannot_be_followed_is_refused(db: Session) -> None:
    services = _direction(db, "services", "Xizmatlar")
    bad = [
        {"goal_first": "sales", "reason_first": "x"},
        {"goal_first": "submarines", "reason_first": "x"},
        {"goal_first": "leads", "reason_first": ""},
        {
            "goal_first": "",
            "reason_first": "",
            "goal_second": "leads",
            "when_second": "x",
        },
        {
            "goal_first": "leads",
            "reason_first": "x",
            "goal_second": "leads",
            "when_second": "x",
        },
        {"goal_first": "leads", "reason_first": "x", "goal_second": "messages"},
        {"goal_first": "leads", "reason_first": "x" * 501},
    ]
    for fields in bad:
        with pytest.raises(BadAdvice):
            advice.save_rule(db, direction=services, **fields)
    assert advice.advice_of(db, direction=services) is None


# -- the knowledge itself ----------------------------------------------------


def test_what_a_business_sells_is_kept_and_changed_in_small_steps(db: Session) -> None:
    world = World(db)
    business = _business(world)

    row = knowledge.apply(
        db,
        business=business,
        changes=[
            {"op": "set_about", "text": "  Ingliz tili va matematika   o'quv markazi "},
            {
                "op": "add_item",
                "name": "Ingliz tili",
                "kind": "course",
                "price": "450 000 so'm / oy",
            },
            {"op": "add_item", "name": "Matematika", "kind": "course"},
            {"op": "set_fact", "key": "area", "value": "Chilonzor"},
        ],
        source=KnowledgeSource.LAUNCH_AGENT,
        actor=world.owner,
    )
    db.commit()

    view = known(db, business)
    assert row.version == view.version == 1
    assert view.does == "Ingliz tili va matematika o'quv markazi"
    assert [item["name"] for item in view.items] == ["Ingliz tili", "Matematika"]
    assert view.facts["area"]["value"] == "Chilonzor"
    english = _items(db, business)["Ingliz tili"]
    assert (english["kind"], english["status"], english["src"]) == (
        "course",
        "active",
        "launch_agent",
    )

    # Named again with a new price: the same item, not a second one.
    knowledge.apply(
        db,
        business=business,
        changes=[
            {"op": "add_item", "name": "ingliz  TILI", "price": "500 000 so'm / oy"},
            {"op": "archive_item", "id": _items(db, business)["Matematika"]["id"]},
            {"op": "clear_fact", "key": "area"},
        ],
        source=KnowledgeSource.ASSISTANT,
    )
    db.commit()

    view = known(db, business)
    assert view.version == 2
    assert len(view.items) == 2
    assert _items(db, business)["Ingliz tili"]["price"] == "500 000 so'm / oy"
    assert [item["name"] for item in view.active_items] == ["Ingliz tili"]
    assert view.facts == {}
    events = db.scalars(
        select(Event)
        .where(Event.name == EventName.BUSINESS_KNOWLEDGE_CHANGED)
        .order_by(Event.occurred_at)
    ).all()
    assert [event.payload["version"] for event in events] == [1, 2]
    assert events[0].payload["by"] == str(world.owner.id)
    update = events[1].payload["changes"][0]
    assert (update["op"], update["before"]["price"], update["after"]["price"]) == (
        "update_item",
        "450 000 so'm / oy",
        "500 000 so'm / oy",
    )


def test_a_change_that_changes_nothing_writes_nothing(db: Session) -> None:
    world = World(db)
    business = _business(world)
    same = [{"op": "add_item", "name": "Divan", "price": "3 mln"}]
    knowledge.apply(db, business=business, changes=same, source="owner")
    row = knowledge.apply(db, business=business, changes=same, source="owner")
    db.commit()

    assert row.version == 1
    assert (
        db.query(Event).filter_by(name=EventName.BUSINESS_KNOWLEDGE_CHANGED).count()
        == 1
    )


def test_all_of_the_changes_land_or_none(db: Session) -> None:
    world = World(db)
    business = _business(world)
    knowledge.apply(
        db,
        business=business,
        changes=[{"op": "add_item", "name": "Divan"}],
        source="owner",
    )
    db.commit()

    with pytest.raises(UnknownItem):
        knowledge.apply(
            db,
            business=business,
            changes=[
                {"op": "add_item", "name": "Kreslo"},
                {"op": "archive_item", "id": "nobody"},
            ],
            source="owner",
        )
    db.rollback()

    assert list(_items(db, business)) == ["Divan"]
    assert known(db, business).version == 1


def test_a_bad_change_is_refused_with_what_is_wrong(db: Session) -> None:
    world = World(db)
    business = _business(world)
    bad = [
        {"op": "paint_it"},
        {"op": "add_item"},
        {"op": "add_item", "name": "x" * 81},
        {"op": "add_item", "name": "Divan", "kind": "spaceship"},
        {"op": "update_item", "id": "a"},
        {"op": "update_item", "name": "Divan"},
        {"op": "set_fact", "key": "mood", "value": "good"},
        {"op": "set_fact", "key": "area", "value": " "},
        {"op": "set_about", "text": "x" * 601},
        {"op": "add_item", "name": 5},
    ]
    for change in bad:
        with pytest.raises(BadKnowledgeChange):
            knowledge.apply(db, business=business, changes=[change], source="owner")
    with pytest.raises(BadKnowledgeChange):
        knowledge.apply(db, business=business, changes=[], source="the moon")
    assert knowledge.row_of(db, business) is None or known(db, business).version == 0


def test_an_item_cannot_take_another_item_s_name(db: Session) -> None:
    world = World(db)
    business = _business(world)
    knowledge.apply(
        db,
        business=business,
        changes=[
            {"op": "add_item", "name": "Divan"},
            {"op": "add_item", "name": "Kreslo"},
        ],
        source="owner",
    )
    kreslo = _items(db, business)["Kreslo"]["id"]

    with pytest.raises(BadKnowledgeChange):
        knowledge.apply(
            db,
            business=business,
            changes=[{"op": "update_item", "id": kreslo, "name": "DIVAN"}],
            source="owner",
        )


def test_a_form_filled_over_an_old_reading_is_told_so(db: Session) -> None:
    world = World(db)
    business = _business(world)
    knowledge.apply(
        db,
        business=business,
        changes=[{"op": "add_item", "name": "Divan"}],
        source="owner",
    )
    db.commit()

    with pytest.raises(KnowledgeMoved):
        knowledge.apply(
            db,
            business=business,
            changes=[{"op": "add_item", "name": "Kreslo"}],
            source="owner",
            expected_version=0,
        )
    knowledge.apply(
        db,
        business=business,
        changes=[{"op": "add_item", "name": "Kreslo"}],
        source="owner",
        expected_version=1,
    )
    assert set(_items(db, business)) == {"Divan", "Kreslo"}


def test_two_chats_adding_at_once_both_land(db: Session, pg_factory) -> None:  # type: ignore[no-untyped-def]
    world = World(db)
    business = _business(world)
    knowledge.apply(
        db,
        business=business,
        changes=[{"op": "add_item", "name": "Divan"}],
        source="owner",
    )
    db.commit()

    with pg_factory() as other:
        theirs = other.get(Business, business.id)
        knowledge.apply(
            other,
            business=theirs,
            changes=[{"op": "add_item", "name": "Kreslo"}],
            source=KnowledgeSource.ASSISTANT,
        )
        other.commit()
    # This session read the document before the other chat wrote to it.
    knowledge.apply(
        db,
        business=business,
        changes=[{"op": "add_item", "name": "Stol"}],
        source=KnowledgeSource.LAUNCH_AGENT,
    )
    db.commit()

    db.expire_all()
    assert set(_items(db, business)) == {"Divan", "Kreslo", "Stol"}
    assert known(db, business).version == 3


def test_the_list_of_things_sold_has_an_end(db: Session) -> None:
    world = World(db)
    business = _business(world)
    knowledge.apply(
        db,
        business=business,
        changes=[{"op": "add_item", "name": f"Mahsulot {n}"} for n in range(MAX_ITEMS)],
        source="owner",
    )

    with pytest.raises(KnowledgeFull):
        knowledge.apply(
            db,
            business=business,
            changes=[{"op": "add_item", "name": "Yana bitta"}],
            source="owner",
        )


def test_what_a_model_worked_out_waits_for_a_yes(db: Session) -> None:
    world = World(db)
    business = _business(world)
    knowledge.apply(
        db,
        business=business,
        changes=[{"op": "add_item", "name": "Ingliz tili", "price": "450 000"}],
        source="owner",
    )
    english = _items(db, business)["Ingliz tili"]["id"]
    change = [{"op": "update_item", "id": english, "price": "500 000"}]

    proposal = knowledge.propose(
        db,
        business=business,
        changes=change,
        source=KnowledgeSource.ASSISTANT,
        why="Suhbatda yangi narx aytildi",
    )
    twice = knowledge.propose(
        db, business=business, changes=change, source=KnowledgeSource.ASSISTANT
    )
    db.commit()

    assert proposal is not None and twice is None
    view = known(db, business)
    assert [one["id"] for one in view.pending] == [proposal["id"]]
    assert _items(db, business)["Ingliz tili"]["price"] == "450 000"

    knowledge.confirm(
        db, business=business, proposal_id=proposal["id"], actor=world.owner
    )
    db.commit()

    view = known(db, business)
    assert view.pending == []
    assert _items(db, business)["Ingliz tili"]["price"] == "500 000"
    assert _items(db, business)["Ingliz tili"]["src"] == "assistant"
    with pytest.raises(UnknownProposal):
        knowledge.confirm(db, business=business, proposal_id=proposal["id"])


def test_a_no_drops_the_proposal_and_changes_nothing_else(db: Session) -> None:
    world = World(db)
    business = _business(world)
    proposal = knowledge.propose(
        db,
        business=business,
        changes=[{"op": "add_item", "name": "Rus tili"}],
        source=KnowledgeSource.ASSISTANT,
    )
    assert proposal is not None

    knowledge.reject(
        db, business=business, proposal_id=proposal["id"], actor=world.owner
    )
    db.commit()

    view = known(db, business)
    assert (view.pending, view.items) == ([], [])
    vias = [
        event.payload["via"]
        for event in db.scalars(
            select(Event)
            .where(Event.name == EventName.BUSINESS_KNOWLEDGE_CHANGED)
            .order_by(Event.occurred_at)
        )
    ]
    assert vias == ["propose", "reject"]


def test_a_proposal_that_can_no_longer_be_applied_stays_to_be_refused(
    db: Session,
) -> None:
    world = World(db)
    business = _business(world)
    proposal = knowledge.propose(
        db,
        business=business,
        changes=[{"op": "archive_item", "id": "gone"}],
        source=KnowledgeSource.ASSISTANT,
    )
    db.commit()
    assert proposal is not None

    with pytest.raises(UnknownItem):
        knowledge.confirm(db, business=business, proposal_id=proposal["id"])
    db.rollback()

    assert [one["id"] for one in known(db, business).pending] == [proposal["id"]]


def test_only_the_newest_proposals_wait(db: Session) -> None:
    world = World(db)
    business = _business(world)
    for n in range(MAX_PENDING + 3):
        knowledge.propose(
            db,
            business=business,
            changes=[{"op": "add_item", "name": f"Taklif {n}"}],
            source=KnowledgeSource.ASSISTANT,
        )
    db.commit()

    waiting = known(db, business).pending
    assert len(waiting) == MAX_PENDING
    assert waiting[0]["changes"][0]["name"] == "Taklif 3"


def test_a_page_s_second_account_shares_the_page_s_knowledge(db: Session) -> None:
    world = World(db)
    first = _business(world)
    page = db.get(Business, first.id).page  # type: ignore[union-attr]
    world.pair(page, world.account("act_2"))
    db.commit()
    (second_id,) = [
        link.business_id for link in world.open_links() if link.business_id != first.id
    ]
    second = db.get(Business, second_id)
    assert second is not None and second.page_id is None

    knowledge.apply(
        db,
        business=second,
        changes=[{"op": "add_item", "name": "Divan"}],
        source="owner",
    )
    db.commit()

    assert knowledge.home(db, second).id == first.id
    assert list(_items(db, first)) == ["Divan"]
    assert known(db, second).version == known(db, first).version == 1
    assert db.query(BusinessKnowledge).count() == 1


# -- the kind of a business --------------------------------------------------


def test_a_business_is_told_its_kind(db: Session) -> None:
    world = World(db)
    business = _business(world)
    mebel = _direction(db)
    kitchen, _ = subtypes.ensure(db, direction=mebel, name="Oshxona mebeli")
    assert known(db, business).type_state == TypeState.UNSET

    kinds.set_kind(
        db,
        business=business,
        direction=mebel,
        subtype=kitchen,
        state=TypeState.GUESSED,
        source=KnowledgeSource.PAGE,
    )
    db.commit()

    view = known(db, business)
    assert (business.direction_id, business.category) == (mebel.id, "furniture")
    assert (view.type_label, view.type_state, view.subtype.name) == (
        "Mebel",
        "guessed",
        "Oshxona mebeli",
    )
    event = db.scalars(
        select(Event).where(Event.name == EventName.BUSINESS_TYPE_SET)
    ).one()
    assert (event.payload["direction_key"], event.payload["subtype_name"]) == (
        "furniture",
        "Oshxona mebeli",
    )


def test_a_guess_never_overwrites_a_kind_somebody_confirmed(db: Session) -> None:
    world = World(db)
    business = _business(world)
    mebel, services = _direction(db), _direction(db, "services", "Xizmatlar")
    kinds.set_kind(db, business=business, direction=mebel, actor=world.owner)

    kinds.set_kind(
        db,
        business=business,
        direction=services,
        state=TypeState.GUESSED,
        source="page",
    )
    db.commit()

    assert business.category == "furniture"
    assert known(db, business).type_state == TypeState.CONFIRMED


def test_a_kind_belongs_to_its_direction(db: Session) -> None:
    world = World(db)
    business = _business(world)
    mebel, services = _direction(db), _direction(db, "services", "Xizmatlar")
    cleaning, _ = subtypes.ensure(db, direction=services, name="Gilam yuvish")

    with pytest.raises(BadSubtype):
        kinds.set_kind(db, business=business, direction=mebel, subtype=cleaning)


def test_a_profile_filled_by_hand_is_a_confirmed_kind(db: Session) -> None:
    world = World(db)
    business = _business(world)
    mebel = _direction(db)
    business.direction_id, business.category = mebel.id, "furniture"
    db.commit()

    view = known(db, business)
    assert (view.type_state, view.type_label, view.version) == ("confirmed", "Mebel", 0)


# -- the words a model is given ----------------------------------------------


def test_the_brief_says_who_the_business_is(db: Session) -> None:
    world = World(db)
    business = _business(world)
    mebel = _direction(db)
    kitchen, _ = subtypes.ensure(db, direction=mebel, name="Oshxona mebeli")
    kinds.set_kind(
        db, business=business, direction=mebel, subtype=kitchen, state="guessed"
    )
    knowledge.apply(
        db,
        business=business,
        changes=[
            {"op": "set_about", "text": "Buyurtma asosida oshxona mebeli"},
            {
                "op": "add_item",
                "name": "Oshxona",
                "price": "3 mln / metr",
                "note": "MDF",
            },
            {"op": "add_item", "name": "Eski model"},
            {"op": "set_fact", "key": "guarantee", "value": "2 yil"},
        ],
        source="owner",
    )
    knowledge.apply(
        db,
        business=business,
        changes=[
            {"op": "archive_item", "id": _items(db, business)["Eski model"]["id"]}
        ],
        source="owner",
    )
    db.commit()

    text = brief(db, business)

    assert text.splitlines()[:3] == [
        "## Business",
        "- Name: Biznes p1",
        "- Kind: Mebel → Oshxona mebeli (our guess, not confirmed by the business)",
    ]
    assert "- What it does: Buyurtma asosida oshxona mebeli" in text
    assert "  - Oshxona — 3 mln / metr — MDF" in text
    assert "  - Guarantee: 2 yil" in text
    assert "Eski model" not in text
    assert "- City: Toshkent" in text


def test_the_brief_keeps_within_its_length(db: Session) -> None:
    world = World(db)
    business = _business(world)
    knowledge.apply(
        db,
        business=business,
        changes=[
            {"op": "add_item", "name": f"Mahsulot {n:02d}", "note": "izoh " * 40}
            for n in range(30)
        ],
        source="owner",
    )
    db.commit()

    assert len(brief(db, business)) <= 1800
    short = brief(db, business, limit=300)
    assert len(short) <= 300 and short.startswith("## Business")
    assert "izoh" not in short


def test_a_business_nothing_is_known_of_still_has_a_brief(db: Session) -> None:
    world = World(db)
    business = _business(world)

    assert brief(db, business) == (
        "## Business\n- Name: Biznes p1\n- City: Toshkent\n- Website: https://example.uz"
    )


# -- over HTTP ---------------------------------------------------------------


def test_the_knowledge_of_a_business_is_read_and_changed(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    services = _direction(db, "services", "Xizmatlar")
    advice.save_rule(
        db,
        direction=services,
        goal_first="leads",
        reason_first="Narx ishni ko'rgandan keyin aytiladi.",
        goal_second="messages",
        when_second="Narx aniq bo'lsa.",
    )
    db.commit()
    owner = _auth(world.owner)
    url = f"{URL}/{business.id}"

    empty = client.get(f"{url}/knowledge", headers=owner)
    assert empty.status_code == 200, empty.text
    body = empty.json()
    assert (body["version"], body["may_edit"], body["kept_by"]) == (
        0,
        True,
        str(business.id),
    )
    assert body["kind"] == {
        "direction": None,
        "label": "",
        "state": "unset",
        "subtype": None,
    }
    assert (body["items"], body["facts"], body["pending"], body["advice"]) == (
        [],
        [],
        [],
        None,
    )

    kind = client.put(
        f"{url}/kind",
        json={"direction": "services", "subtype": "Gilam yuvish"},
        headers=owner,
    )
    assert kind.status_code == 200, kind.text
    assert kind.json()["kind"]["state"] == "confirmed"
    assert kind.json()["kind"]["direction"] == {"key": "services", "label": "Xizmatlar"}
    assert kind.json()["kind"]["subtype"]["name"] == "Gilam yuvish"
    assert kind.json()["kind"]["subtype"]["is_checked"] is False
    assert kind.json()["advice"]["goal_first"] == {
        "key": "leads",
        "label": "Ariza yig'ish (lid forma)",
    }
    assert kind.json()["advice"]["goal_second"]["key"] == "messages"

    changed = client.post(
        f"{url}/knowledge/changes",
        json={
            "changes": [
                {
                    "op": "add_item",
                    "name": "Gilam yuvish",
                    "kind": "service",
                    "price": "12 000 so'm / m²",
                },
                {
                    "op": "set_fact",
                    "key": "delivery",
                    "value": "Olib ketamiz va qaytaramiz",
                },
            ]
        },
        headers=owner,
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    (item,) = body["items"]
    assert (item["name"], item["kind_label"], item["source"], item["source_label"]) == (
        "Gilam yuvish",
        "Xizmat",
        "owner",
        "Biznes egasi",
    )
    assert body["facts"][0]["label"] == "Yetkazib berish"
    # Setting the kind made the row and is no change of the document: this is its first.
    assert body["version"] == 1

    stale = client.post(
        f"{url}/knowledge/changes",
        json={"changes": [{"op": "set_about", "text": "Gilam yuvamiz"}], "version": 0},
        headers=owner,
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "knowledge_moved")
    bad = client.post(
        f"{url}/knowledge/changes",
        json={"changes": [{"op": "archive_item", "id": "nobody"}]},
        headers=owner,
    )
    assert (bad.status_code, bad.json()["code"]) == (404, "unknown_item")
    wrong = client.post(
        f"{url}/knowledge/changes",
        json={"changes": [{"op": "set_fact", "key": "mood", "value": "x"}]},
        headers=owner,
    )
    assert (wrong.status_code, wrong.json()["code"]) == (400, "bad_knowledge_change")

    picker = client.get(f"{url}/knowledge/subtypes", headers=owner).json()
    assert [row["name"] for row in picker["subtypes"]] == ["Gilam yuvish"]
    history = client.get(f"{url}/knowledge/history", headers=owner).json()["items"]
    assert [row["kind"] for row in history] == ["knowledge_changed", "type_set"]
    assert history[0]["lines"] == [
        "Yangi taklif: Gilam yuvish — 12 000 so'm / m²",
        "Yetkazib berish: Olib ketamiz va qaytaramiz",
    ]
    assert history[0]["by_name"] == "Ega"
    assert history[1]["lines"] == ["Biznes turi: Xizmatlar → Gilam yuvish"]


def test_a_proposal_is_answered_over_http(client: TestClient, db: Session) -> None:
    world = World(db)
    business = _business(world)
    one = knowledge.propose(
        db,
        business=business,
        changes=[{"op": "add_item", "name": "Rus tili", "price": "400 000"}],
        source=KnowledgeSource.ASSISTANT,
        why="Suhbatda aytildi",
    )
    two = knowledge.propose(
        db,
        business=business,
        changes=[{"op": "set_fact", "key": "guarantee", "value": "1 yil"}],
        source=KnowledgeSource.LAUNCH_AGENT,
    )
    db.commit()
    assert one is not None and two is not None
    owner = _auth(world.owner)
    url = f"{URL}/{business.id}/knowledge"

    waiting = client.get(url, headers=owner).json()["pending"]
    assert [row["lines"] for row in waiting] == [
        ["Yangi taklif: Rus tili — 400 000"],
        ["Kafolat: 1 yil"],
    ]
    assert waiting[0]["source_label"] == "AI chat"

    yes = client.post(f"{url}/proposals/{one['id']}/confirm", headers=owner)
    no = client.post(f"{url}/proposals/{two['id']}/reject", headers=owner)
    gone = client.post(f"{url}/proposals/{two['id']}/reject", headers=owner)

    assert (yes.status_code, no.status_code) == (200, 200)
    assert (gone.status_code, gone.json()["code"]) == (404, "unknown_proposal")
    body = no.json()
    assert [item["name"] for item in body["items"]] == ["Rus tili"]
    assert (body["facts"], body["pending"]) == ([], [])


def test_who_may_read_and_who_may_change(client: TestClient, db: Session) -> None:
    world, other = World(db), World(db, "boshqa@example.com")
    business = _business(world)
    reader, editor = _staff(world, "Oquvchi"), _staff(world, "Sotuvchi")
    add_member(
        db,
        business=business,
        user=reader,
        roles=["sales"],
        grants={("crm", "meta"): "view"},
    )
    add_member(db, business=business, user=editor, roles=["sales"])
    db.commit()
    url = f"{URL}/{business.id}"
    change = {"changes": [{"op": "add_item", "name": "Divan"}]}

    assert client.get(f"{url}/knowledge").status_code == 401
    assert client.get(f"{url}/knowledge", headers=_auth(other.owner)).status_code == 404
    seen = client.get(f"{url}/knowledge", headers=_auth(reader))
    assert seen.status_code == 200 and seen.json()["may_edit"] is False
    refused = client.post(
        f"{url}/knowledge/changes", json=change, headers=_auth(reader)
    )
    assert (refused.status_code, refused.json()["code"]) == (403, "no_access")
    assert (
        client.put(
            f"{url}/kind", json={"direction": "services"}, headers=_auth(reader)
        ).status_code
        == 403
    )

    written = client.post(
        f"{url}/knowledge/changes", json=change, headers=_auth(editor)
    )
    assert written.status_code == 200, written.text
    assert written.json()["items"][0]["source"] == "member"
    assert written.json()["may_edit"] is True


def test_a_kind_is_set_only_to_what_exists(client: TestClient, db: Session) -> None:
    world = World(db)
    business = _business(world)
    mebel, services = _direction(db), _direction(db, "services", "Xizmatlar")
    off = _direction(db, "kids", "Bolalar")
    off.is_active = False
    cleaning, _ = subtypes.ensure(db, direction=services, name="Gilam yuvish")
    db.commit()
    owner = _auth(world.owner)
    url = f"{URL}/{business.id}/kind"

    for direction in ("submarines", "kids"):
        missing = client.put(url, json={"direction": direction}, headers=owner)
        assert (missing.status_code, missing.json()["code"]) == (
            404,
            "unknown_direction",
        )
    foreign = client.put(
        url,
        json={"direction": mebel.key, "subtype_id": str(cleaning.id)},
        headers=owner,
    )
    assert (foreign.status_code, foreign.json()["code"]) == (400, "bad_subtype")
    db.expire_all()
    assert db.get(Business, business.id).direction_id is None  # type: ignore[union-attr]

    plain = client.put(url, json={"direction": mebel.key}, headers=owner)
    assert plain.status_code == 200 and plain.json()["kind"]["subtype"] is None


def test_the_lists_a_knowledge_form_is_built_from(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    _direction(db)
    db.commit()

    body = client.get(f"{URL}/knowledge/catalog", headers=_auth(world.owner)).json()

    assert body["directions"] == [{"key": "furniture", "label": "Mebel"}]
    assert {"key": "course", "label": "Kurs yoki yo'nalish"} in body["item_kinds"]
    assert {"key": "guarantee", "label": "Kafolat"} in body["fact_keys"]
    assert "add_item" in body["ops"]
    assert body["limits"]["items"] == MAX_ITEMS


# -- the office --------------------------------------------------------------


def test_the_office_writes_what_a_direction_is_advised(
    client: TestClient, db: Session
) -> None:
    _, keeper = _office(db, Role.ENGINEER, email="eng@office.test")
    _, support = _office(db, Role.SUPPORT, email="sup@office.test")
    services = _direction(db, "services", "Xizmatlar")
    db.commit()
    url = f"{OFFICE}/business-types"

    assert client.get(url).status_code == 401
    assert client.get(url, headers=support).status_code == 404
    listed = client.get(url, headers=keeper)
    assert listed.status_code == 200, listed.text
    (row,) = listed.json()["rows"]
    assert (row["key"], row["is_advised"], row["rule"]["goal_first"]) == (
        "services",
        False,
        None,
    )
    offered = {goal["value"] for goal in row["goals"]}
    assert {"leads", "messages", "telegram"} <= offered and "sales" not in offered

    rule = {
        "goal_first": "leads",
        "reason_first": "Narx ishni ko'rgandan keyin aytiladi.",
        "goal_second": "messages",
        "when_second": "Narx aniq bo'lsa.",
        "never_say": "Natijani kafolatlash.",
    }
    assert (
        client.put(f"{url}/{services.id}/rule", json=rule, headers=support).status_code
        == 404
    )
    saved = client.put(f"{url}/{services.id}/rule", json=rule, headers=keeper)
    assert saved.status_code == 200, saved.text
    assert saved.json()["rule"]["goal_second"] == {
        "key": "messages",
        "label": "Xabar yozishsin",
    }
    bad = client.put(
        f"{url}/{services.id}/rule", json=rule | {"goal_first": "sales"}, headers=keeper
    )
    assert (bad.status_code, bad.json()["code"]) == (400, "bad_advice")

    (row,) = client.get(url, headers=keeper).json()["rows"]
    assert (row["is_advised"], row["rule"]["never_say"]) == (
        True,
        "Natijani kafolatlash.",
    )
    kinds_written = [
        action.kind
        for action in db.scalars(select(StaffAction).order_by(StaffAction.created_at))
    ]
    assert kinds_written == [ActionKind.TYPE_RULE_SAVED]


def test_the_office_looks_after_the_narrower_kinds(
    client: TestClient, db: Session
) -> None:
    _, keeper = _office(db, Role.OWNER, email="own@office.test")
    world = World(db)
    business = _business(world)
    mebel = _direction(db)
    made_by_ai, _ = subtypes.ensure(db, direction=mebel, name="Kuxnya mebel")
    kinds.set_kind(db, business=business, direction=mebel, subtype=made_by_ai)
    db.commit()
    url = f"{OFFICE}/business-types/{mebel.id}/subtypes"

    made = client.post(
        url, json={"name": "Oshxona mebeli", "synonyms": ["kuxnya"]}, headers=keeper
    )
    assert made.status_code == 201, made.text
    kitchen = made.json()["subtype"]
    assert (made.json()["created"], kitchen["origin"], kitchen["is_checked"]) == (
        True,
        "staff",
        True,
    )
    again = client.post(url, json={"name": "KUXNYA"}, headers=keeper)
    assert (again.json()["created"], again.json()["subtype"]["id"]) == (
        False,
        kitchen["id"],
    )

    rows = client.get(url, headers=keeper).json()["rows"]
    assert [(row["name"], row["is_checked"], row["businesses"]) for row in rows] == [
        ("Kuxnya mebel", False, 1),
        ("Oshxona mebeli", True, 0),
    ]
    (type_row,) = client.get(f"{OFFICE}/business-types", headers=keeper).json()["rows"]
    assert (
        type_row["subtypes"],
        type_row["unchecked_subtypes"],
        type_row["businesses"],
    ) == (2, 1, 1)

    merged = client.post(
        f"{OFFICE}/business-subtypes/{made_by_ai.id}/merge",
        json={"into_id": kitchen["id"]},
        headers=keeper,
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["subtype"]["synonyms"] == ["kuxnya", "Kuxnya mebel"]
    rows = client.get(url, headers=keeper).json()["rows"]
    assert [(row["name"], row["businesses"]) for row in rows] == [("Oshxona mebeli", 1)]
    assert len(client.get(f"{url}?merged=true", headers=keeper).json()["rows"]) == 2
    twice = client.post(
        f"{OFFICE}/business-subtypes/{made_by_ai.id}/merge",
        json={"into_id": kitchen["id"]},
        headers=keeper,
    )
    assert (twice.status_code, twice.json()["code"]) == (400, "bad_subtype")

    patched = client.patch(
        f"{OFFICE}/business-subtypes/{kitchen['id']}",
        json={"name": "Oshxona mebeli (buyurtma)", "is_active": False},
        headers=keeper,
    )
    assert patched.status_code == 200, patched.text
    assert (
        patched.json()["subtype"]["name"],
        patched.json()["subtype"]["is_active"],
    ) == (
        "Oshxona mebeli (buyurtma)",
        False,
    )
    assert (
        client.patch(
            f"{OFFICE}/business-subtypes/{kitchen['id']}",
            json={"name": " "},
            headers=keeper,
        ).status_code
        == 400
    )
    owner_view = client.get(
        f"{URL}/{business.id}/knowledge", headers=_auth(world.owner)
    ).json()
    assert owner_view["kind"]["subtype"]["name"] == "Oshxona mebeli (buyurtma)"
