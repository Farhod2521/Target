"""One business of a customer's from their office card, against PostgreSQL:
what it is made of, and each part taken away on its own - the AI's
knowledge, the CRM, a network, the place in the subscription - and the
business itself."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.backoffice.models import StaffAction
from app.modules.businesses.constants import KnowledgeSource, TypeState
from app.modules.businesses.models import (
    Business,
    BusinessCategory,
    BusinessLink,
    BusinessMember,
)
from app.modules.businesses.selectors.knowledge import known
from app.modules.businesses.services import knowledge
from app.modules.businesses.services.kinds import set_kind
from app.modules.crm.models import CrmCard, CrmMember, CrmSetup, CrmStage
from app.modules.integrations.models import PageAccount, PagePair
from app.modules.leads.models import Lead
from tests.pg.test_business_links import World
from tests.pg.test_business_members import _business, _manager
from tests.pg.test_business_v3 import _paid
from tests.pg.test_office_crm import _staff

URL = "/api/v1/office/customers"
WHY = "Mijoz so'radi"


def _two(db: Session) -> tuple[World, Business, Business, dict[str, str]]:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)
    return world, first, second, _staff(db, Role.OWNER, "boss@example.com")


def _post(
    client: TestClient,
    world: World,
    head: dict[str, str],
    business: Business | Any,
    path: str,
    **body: Any,
) -> Any:
    pk = business.id if isinstance(business, Business) else business
    return client.post(
        f"{URL}/{world.owner.id}/businesses/{pk}{path}",
        json={"reason": WHY, **body},
        headers=head,
    )


def _listed(client: TestClient, world: World, head: dict[str, str]) -> dict[str, Any]:
    answer = client.get(f"{URL}/{world.owner.id}/businesses", headers=head)
    assert answer.status_code == 200, answer.text
    return {row["id"]: row for row in answer.json()["businesses"]}


def _kinds(db: Session, owner: User) -> list[str]:
    db.expire_all()
    return [
        row.kind
        for row in db.scalars(
            select(StaffAction)
            .where(StaffAction.owner_id == owner.id)
            .order_by(StaffAction.created_at)
        )
        if row.kind != ActionKind.VIEW
    ]


def _link(world: World, business: Business) -> BusinessLink:
    return next(row for row in world.open_links() if row.business_id == business.id)


def _board(world: World, business: Business, phone: str) -> Lead:
    """The pair's CRM set up, with one lead on a card."""
    link = _link(world, business)
    pair = {
        "owner_id": world.owner.id,
        "page_id": link.page_id,
        "ad_account_id": link.ad_account_id,
    }
    stage = CrmStage(**pair, name="Yangi", color="#000000", kind="new", position=0)
    lead = Lead(
        owner_id=world.owner.id,
        provider="meta",
        leadgen_id=f"lead:{phone}",
        full_name="Mijoz",
        phone_e164=phone,
        submitted_at=world.now,
        received_at=world.now,
        business_id=business.id,
    )
    world.db.add_all([stage, lead, CrmSetup(**pair, state="on")])
    world.db.flush()
    world.db.add(CrmCard(**pair, lead_id=lead.id, stage_id=stage.id))
    world.db.commit()
    return lead


def test_the_card_lists_the_customer_s_businesses(
    client: TestClient, db: Session
) -> None:
    world, first, second, head = _two(db)
    _board(world, first, "+998900000001")

    listed = _listed(client, world, head)

    assert set(listed) == {str(first.id), str(second.id)}
    row = listed[str(first.id)]
    assert (row["name"], row["pair"]) == ("Biznes p1", "p1:act_1")
    assert row["page"]["external_id"] == "p1" and row["page"]["subscribed"] is True
    assert [(one["provider"], one["kind"]) for one in row["networks"]] == [
        ("meta", "meta_pair")
    ]
    assert row["crm"] == {"state": "on", "cards": 1}
    assert listed[str(second.id)]["crm"] == {"state": "none", "cards": 0}
    assert row["knowledge"] == {
        "kind_state": "unset",
        "by_ai": 0,
        "by_people": 0,
        "pending": 0,
    }
    # Somebody else's business is no part of this card.
    other = World(db, "boshqa@example.com")
    theirs = _business(other, "p9", "act_9")
    assert _post(client, world, head, theirs, "/knowledge/clear").status_code == 404
    # Staff only.
    from tests.pg.test_business_v3 import _auth

    shut = client.get(f"{URL}/{world.owner.id}/businesses", headers=_auth(world.owner))
    assert shut.status_code in (401, 403, 404)


def test_what_the_ai_wrote_is_cleared_and_what_people_wrote_stays(
    client: TestClient, db: Session
) -> None:
    world, first, _second, head = _two(db)
    education = BusinessCategory(
        key="education", label_uz="Ta'lim", preset_key="education"
    )
    db.add(education)
    db.flush()
    set_kind(
        db,
        business=first,
        direction=education,
        state=TypeState.GUESSED,
        source=KnowledgeSource.PAGE,
    )
    knowledge.apply(
        db,
        business=first,
        source=KnowledgeSource.OWNER,
        changes=[{"op": "add_item", "name": "IELTS kursi", "price": "800 000 so'm"}],
    )
    knowledge.apply(
        db,
        business=first,
        source=KnowledgeSource.PAGE,
        changes=[
            {"op": "set_about", "text": "Ingliz tili o'quv markazi"},
            {"op": "add_item", "name": "Matematika kursi"},
        ],
    )
    knowledge.propose(
        db,
        business=first,
        source=KnowledgeSource.ASSISTANT,
        changes=[{"op": "add_item", "name": "Rus tili kursi"}],
        why="Suhbatda aytildi",
    )
    db.commit()
    before = _listed(client, world, head)[str(first.id)]["knowledge"]
    assert before == {"kind_state": "guessed", "by_ai": 2, "by_people": 1, "pending": 1}

    done = _post(client, world, head, first, "/knowledge/clear")

    assert done.status_code == 200, done.text
    assert done.json()["cleared"] == {
        "about": 1,
        "items": 1,
        "facts": 0,
        "pending": 1,
        "kind": 1,
    }
    db.expire_all()
    view = known(db, first)
    assert [item["name"] for item in view.items] == ["IELTS kursi"]
    assert view.does == "" and view.type_state == TypeState.UNSET
    after = _listed(client, world, head)[str(first.id)]["knowledge"]
    assert after == {"kind_state": "unset", "by_ai": 0, "by_people": 1, "pending": 0}
    assert _kinds(db, world.owner) == [ActionKind.BUSINESS_AI_CLEARED]
    # Nothing left to clear is said, not an error.
    again = _post(client, world, head, first, "/knowledge/clear")
    assert again.json()["message"] == "AI yozgan ma'lumot yo'q edi."
    # The reason is asked.
    bare = client.post(
        f"{URL}/{world.owner.id}/businesses/{first.id}/knowledge/clear",
        json={},
        headers=head,
    )
    assert bare.status_code == 422


def test_one_business_s_crm_is_erased_and_the_other_s_stays(
    client: TestClient, db: Session
) -> None:
    world, first, second, head = _two(db)
    lead = _board(world, first, "+998900000001")
    kept = _board(world, second, "+998900000002")
    gone_manager = _manager(world, first, "vali")
    stays_manager = _manager(world, second, "gulnora")
    vali, gulnora = gone_manager.user_id, stays_manager.user_id
    db.commit()

    # Support may not: it is the Owner's press, as erasing the whole CRM is.
    support = _staff(db, Role.SUPPORT, "support@example.com")
    refused = _post(client, world, support, first, "/crm/erase")
    assert refused.status_code in (403, 404)
    assert db.scalar(select(func.count()).select_from(CrmCard)) == 2

    done = _post(client, world, head, first, "/crm/erase")

    assert done.status_code == 200, done.text
    assert (
        done.json()["message"] == "Biznes CRM'i o'chirildi: 1 ta karta, 1 ta menejer."
    )
    db.expire_all()
    link = _link(world, second)
    for model in (CrmCard, CrmStage, CrmSetup, CrmMember):
        rows = list(db.scalars(select(model).where(model.owner_id == world.owner.id)))
        assert [(row.page_id, row.ad_account_id) for row in rows] == [
            (link.page_id, link.ad_account_id)
        ], model.__name__
    # The leads stay; the manager who worked nowhere else has no login.
    assert db.get(Lead, lead.id) is not None and db.get(Lead, kept.id) is not None
    assert db.get(User, vali) is None and db.get(User, gulnora) is not None
    members = {
        row.user_id: row.is_active
        for row in db.scalars(
            select(BusinessMember).where(BusinessMember.owner_id == world.owner.id)
        )
    }
    assert members.get(gulnora) is True and members.get(vali) in (None, False)
    listed = _listed(client, world, head)
    assert listed[str(first.id)]["crm"] == {"state": "none", "cards": 0}
    assert listed[str(second.id)]["crm"] == {"state": "on", "cards": 1}
    assert _kinds(db, world.owner) == [ActionKind.BUSINESS_CRM_ERASED]


def test_the_board_is_stopped_and_started_by_its_business(
    client: TestClient, db: Session
) -> None:
    world, first, second, head = _two(db)
    _board(world, first, "+998900000001")
    _board(world, second, "+998900000002")

    stopped = _post(client, world, head, first, "/crm/state", on=False)

    assert stopped.status_code == 200, stopped.text
    listed = _listed(client, world, head)
    assert listed[str(first.id)]["crm"]["state"] == "off"
    assert listed[str(second.id)]["crm"]["state"] == "on"
    started = _post(client, world, head, first, "/crm/state", on=True)
    assert started.status_code == 200, started.text
    assert _listed(client, world, head)[str(first.id)]["crm"]["state"] == "on"


def test_the_meta_pair_is_untied_and_the_page_and_account_stay(
    client: TestClient, db: Session
) -> None:
    world, first, second, head = _two(db)
    page_id = _link(world, first).page_id

    done = _post(client, world, head, first, "/networks/meta/remove")

    assert done.status_code == 200, done.text
    db.expire_all()
    assert db.scalar(select(PagePair.id).where(PagePair.page_id == page_id)) is None
    assert db.get(PageAccount, page_id) is not None
    assert {row.business_id for row in world.open_links()} == {second.id}
    assert db.get(Business, first.id) is not None
    assert _kinds(db, world.owner) == [ActionKind.BUSINESS_NETWORK_REMOVED]
    # Nothing left to untie.
    again = _post(client, world, head, first, "/networks/meta/remove")
    assert (again.status_code, again.json()["code"]) == (409, "business_has_no_pair")
    missing = _post(client, world, head, second, "/networks/google/remove")
    assert (missing.status_code, missing.json()["code"]) == (404, "unknown_network")


def test_a_business_leaves_the_subscription_comes_back_and_hands_its_place_on(
    client: TestClient, db: Session
) -> None:
    world, first, second, head = _two(db)
    one, two = _link(world, first).page_id, _link(world, second).page_id
    # The plan holds one page; the second was given past it.
    from app.modules.billing.models import Subscription

    held = db.scalars(
        select(Subscription).where(Subscription.owner_id == world.owner.id)
    ).one()
    held.extra_pages = 1
    db.commit()

    def subscribed() -> tuple[bool, bool]:
        db.expire_all()
        return (
            bool(db.get(PageAccount, one).is_active),  # type: ignore[union-attr]
            bool(db.get(PageAccount, two).is_active),  # type: ignore[union-attr]
        )

    assert subscribed() == (True, True)
    removed = _post(client, world, head, second, "/subscription/remove")
    assert removed.status_code == 200, removed.text
    assert subscribed() == (True, False)
    assert _listed(client, world, head)[str(second.id)]["page"]["subscribed"] is False

    moved = _post(
        client, world, head, first, "/subscription/move", target=str(second.id)
    )
    assert moved.status_code == 200, moved.text
    assert subscribed() == (False, True)

    back = _post(client, world, head, first, "/subscription/add")
    assert back.status_code == 200, back.text
    assert subscribed() == (True, True)
    # With no place free it is refused, and says why.
    held.extra_pages = 0
    db.commit()
    assert _post(client, world, head, first, "/subscription/remove").status_code == 200
    assert _post(client, world, head, first, "/subscription/add").json()["code"] == (
        "no_free_slot"
    )
    assert _kinds(db, world.owner) == [
        ActionKind.BUSINESS_UNSUBSCRIBED,
        ActionKind.BUSINESS_SLOT_MOVED,
        ActionKind.BUSINESS_SUBSCRIBED,
        ActionKind.BUSINESS_UNSUBSCRIBED,
    ]
    # Nothing was lost on the way.
    assert {row.business_id for row in world.open_links()} == {first.id, second.id}


def test_a_business_is_deleted_whole_and_the_other_is_untouched(
    client: TestClient, db: Session
) -> None:
    world, first, second, head = _two(db)
    lead = _board(world, first, "+998900000001").id
    first_id, second_id = first.id, second.id
    _board(world, second, "+998900000002")
    vali = _manager(world, first, "vali").user_id
    page_id, account_id = _link(world, first).page_id, _link(world, first).ad_account_id
    knowledge.apply(
        db,
        business=first,
        source=KnowledgeSource.OWNER,
        changes=[{"op": "add_item", "name": "IELTS kursi"}],
    )
    db.commit()

    wrong = _post(client, world, head, first, "/delete", email="xato@example.com")
    assert wrong.json()["code"] == "business_email_mismatch"
    db.expire_all()
    assert db.get(Business, first_id) is not None

    done = _post(client, world, head, first, "/delete", email=world.owner.email)

    assert done.status_code == 200, done.text
    gone = done.json()["deleted"]
    assert (gone["networks"], gone["members"], gone["leads"]) == (["meta"], 1, 0)
    assert gone["page_released"] is True and gone["crm"]["cards"] == 1
    db.expire_all()
    assert db.get(Business, first_id) is None
    assert {row.business_id for row in world.open_links()} == {second_id}
    assert db.scalar(select(PagePair.id).where(PagePair.page_id == page_id)) is None
    # The page and the account stay connected, out of the subscription.
    page = db.get(PageAccount, page_id)
    assert page is not None and page.is_active is False
    from app.modules.integrations.models import AdAccount

    assert db.get(AdAccount, account_id) is not None
    assert db.get(User, vali) is None
    # Its leads stay, tied to no business.
    left = db.get(Lead, lead)
    assert left is not None and left.business_id is None
    # The other business is as it was.
    assert db.get(Business, second_id) is not None
    cards = db.scalar(
        select(func.count())
        .select_from(CrmCard)
        .where(CrmCard.owner_id == world.owner.id)
    )
    assert cards == 1
    assert set(_listed(client, world, head)) == {str(second_id)}
    assert _kinds(db, world.owner) == [ActionKind.BUSINESS_DELETED]


def test_a_business_is_deleted_with_its_leads_when_asked(
    client: TestClient, db: Session
) -> None:
    world, first, second, head = _two(db)
    lead = _board(world, first, "+998900000001").id
    kept = _board(world, second, "+998900000002").id

    done = _post(
        client, world, head, first, "/delete", email=world.owner.email, with_leads=True
    )

    assert done.status_code == 200, done.text
    assert done.json()["deleted"]["leads"] == 1
    db.expire_all()
    assert db.get(Lead, lead) is None and db.get(Lead, kept) is not None
