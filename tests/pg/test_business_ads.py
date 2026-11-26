"""A request that names its business (``X-Business``), against PostgreSQL:
the owner reads that business's adverts without moving the cabinet, and a
member with a grant over the adverts works them as the owner would."""

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.acting import Acting, acting_for, override
from app.modules.accounts.models import User
from app.modules.ads.models import Campaign
from app.modules.audit.models import Event
from app.modules.audit.services import emit
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.integrations.selectors import (
    active_ad_account,
    active_page,
    current_pair,
)
from tests.pg.test_business_links import World
from tests.pg.test_business_members import _business
from tests.pg.test_business_v3 import URL, _auth, _new_login, _paid

LIST = "/api/v1/campaigns"
FIRST, SECOND = 2, 1


def _two(db: Session) -> tuple[World, Business, Business]:
    """Two businesses of one owner; the cabinet stands on the first. The
    first account holds two campaigns and the second one, none of them on a
    page yet: the list counts those apart, which tells the accounts apart."""
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)
    for link in world.open_links():
        on_first = link.business_id == first.id
        page = db.get(PageAccount, link.page_id)
        account = db.get(AdAccount, link.ad_account_id)
        assert page is not None and account is not None
        page.is_current = account.is_current = on_first
        for n in range(FIRST if on_first else SECOND):
            db.add(
                Campaign(
                    owner_id=world.owner.id,
                    provider=PROVIDER,
                    external_id=f"c_{account.external_id}_{n}",
                    ad_account_id=account.id,
                    name=f"Kampaniya {n}",
                    delivery="active",
                    status="ACTIVE",
                    currency="USD",
                    synced_at=world.now,
                )
            )
    db.commit()
    return world, first, second


def _on(user: User, business: Business | None = None) -> dict[str, str]:
    headers = _auth(user)
    if business is not None:
        headers["X-Business"] = str(business.id)
    return headers


def _found(client: TestClient, headers: dict[str, str]) -> int:
    """How many campaigns the list finds on the account it reads."""
    answer = client.get(LIST, headers=headers, params={"period": "30d"})
    assert answer.status_code == 200, answer.text
    return int(answer.json()["unplaced"])


def _targetolog(
    client: TestClient, world: World, business: Business, **more: object
) -> User:
    made = client.post(
        f"{URL}/{business.id}/members",
        json=_new_login("Ali", ["targetolog"], **more),
        headers=_auth(world.owner),
    )
    assert made.status_code == 201, made.text
    user = world.db.get(User, made.json()["members"][0]["user"]["id"])
    assert user is not None
    return user


def test_the_owner_reads_the_business_they_name_and_the_cabinet_stays(
    client: TestClient, db: Session
) -> None:
    world, first, second = _two(db)

    assert _found(client, _on(world.owner)) == FIRST
    assert _found(client, _on(world.owner, second)) == SECOND
    assert _found(client, _on(world.owner, first)) == FIRST

    # Nothing was written: the cabinet is where it was.
    db.expire_all()
    current = db.scalars(
        select(AdAccount.external_id).where(AdAccount.is_current.is_(True))
    ).all()
    assert current == ["act_1"]
    assert _found(client, _on(world.owner)) == FIRST


def test_a_targetolog_reads_and_works_the_adverts_of_their_business_only(
    client: TestClient, db: Session
) -> None:
    world, first, second = _two(db)
    ali = _targetolog(client, world, second)

    assert _found(client, _on(ali, second)) == SECOND

    # The figures and the launch open the same way.
    for path in ("/api/v1/metrics/numbers", "/api/v1/campaigns/manager"):
        opened = client.get(path, headers=_on(ali, second))
        assert opened.status_code == 200, (path, opened.text)

    # No business named: a member's login is shut out, as it always was.
    assert client.get(LIST, headers=_on(ali)).status_code == 403
    # A business they do not work in does not exist for them.
    other = client.get(LIST, headers=_on(ali, first))
    assert (other.status_code, other.json()["code"]) == (404, "unknown_business")
    # Outside the adverts the header opens nothing.
    for path in ("/api/v1/billing", "/api/v1/connections", "/api/v1/business"):
        assert client.get(path, headers=_on(ali, second)).status_code == 403, path
    wrong = client.get(LIST, headers={**_auth(ali), "X-Business": "not-an-id"})
    assert wrong.status_code == 404


def test_a_grant_to_read_does_not_let_a_member_change(
    client: TestClient, db: Session
) -> None:
    world, _, second = _two(db)
    ali = _targetolog(
        client,
        world,
        second,
        grants=[{"area": "ads", "provider": "meta", "level": "view"}],
    )

    assert _found(client, _on(ali, second)) == SECOND
    refused = client.post(f"{LIST}/sync", headers=_on(ali, second))
    assert (refused.status_code, refused.json()["code"]) == (403, "no_access")


def test_a_sales_manager_has_no_way_into_the_adverts(
    client: TestClient, db: Session
) -> None:
    world, _, second = _two(db)
    made = client.post(
        f"{URL}/{second.id}/members",
        json=_new_login("Vali", ["sales"]),
        headers=_auth(world.owner),
    )
    assert made.status_code == 201, made.text
    vali = db.get(User, made.json()["members"][0]["user"]["id"])
    assert vali is not None

    refused = client.get(LIST, headers=_on(vali, second))

    assert (refused.status_code, refused.json()["code"]) == (403, "no_access")


def test_a_member_taken_out_is_shut_out_at_once(
    client: TestClient, db: Session
) -> None:
    world, _, second = _two(db)
    ali = _targetolog(client, world, second)
    assert _found(client, _on(ali, second)) == SECOND
    members = client.get(f"{URL}/{second.id}/members", headers=_auth(world.owner))
    member_id = members.json()["members"][0]["id"]

    client.delete(f"{URL}/{second.id}/members/{member_id}", headers=_auth(world.owner))

    assert client.get(LIST, headers=_on(ali, second)).status_code in (401, 404)


def test_the_named_business_is_what_the_cabinet_s_selectors_answer(
    db: Session,
) -> None:
    world, first, second = _two(db)
    link = next(row for row in world.open_links() if row.business_id == second.id)
    held = Acting(
        business_id=second.id,
        owner_id=world.owner.id,
        actor_id=world.owner.id,
        page_id=link.page_id,
        ad_account_id=link.ad_account_id,
    )

    def standing() -> tuple[str, str, str]:
        page = active_page(db, owner=world.owner)
        account = active_ad_account(db, owner=world.owner)
        pair = current_pair(db, owner=world.owner)
        assert page is not None and account is not None and pair is not None
        return page.external_id, account.external_id, pair.key

    assert standing() == ("p1", "act_1", "p1:act_1")
    with override(held):
        assert standing() == ("p2", "act_2", "p2:act_2")
        # Somebody else's request is not answered about this business.
        assert acting_for(first.id) is None
    assert standing() == ("p1", "act_1", "p1:act_1")


def test_what_a_member_does_is_written_under_the_owner_with_their_name(
    db: Session,
) -> None:
    world, _, second = _two(db)
    member = User(
        email="ali@example.com",
        full_name="Ali",
        password="!",
        date_joined=world.now,
        crm_owner_id=world.owner.id,
    )
    db.add(member)
    db.flush()
    held = Acting(
        business_id=second.id,
        owner_id=world.owner.id,
        actor_id=member.id,
        page_id=None,
        ad_account_id=None,
    )

    with override(held):
        by_member = emit(
            db,
            owner_id=world.owner.id,
            name="campaign.paused",
            aggregate_type="campaign",
            aggregate_id="c_2",
            payload={"why": "sinov"},
        )
    by_owner = emit(
        db,
        owner_id=world.owner.id,
        name="campaign.paused",
        aggregate_type="campaign",
        aggregate_id="c_1",
    )
    db.commit()

    assert by_member.payload == {
        "why": "sinov",
        "acting_user_id": str(member.id),
        "business_id": str(second.id),
    }
    assert by_owner.payload == {}
    assert db.scalars(select(Event.owner_id).distinct()).all() == [world.owner.id]


def test_a_member_cannot_reach_another_business_s_advert_by_its_id(
    client: TestClient, db: Session
) -> None:
    from app.modules.ads.selectors.actions import managed_target

    world, _, second = _two(db)
    ali = _targetolog(client, world, second)
    link = next(row for row in world.open_links() if row.business_id == second.id)
    theirs, others = "c_act_2_0", "c_act_1_0"

    def found(actor: User, external_id: str) -> bool:
        held = Acting(
            business_id=second.id,
            owner_id=world.owner.id,
            actor_id=actor.id,
            page_id=link.page_id,
            ad_account_id=link.ad_account_id,
        )
        with override(held):
            return (
                managed_target(
                    db, owner=world.owner, level="campaign", external_id=external_id
                )
                is not None
            )

    assert found(ali, theirs) and not found(ali, others)
    # The owner, naming a business, still reaches every advert that is theirs.
    assert found(world.owner, theirs) and found(world.owner, others)
