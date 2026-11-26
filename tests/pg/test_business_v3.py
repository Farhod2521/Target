"""``/api/v3/businesses`` over HTTP, against PostgreSQL: what the owner, a
member and a stranger are shown, and the owner's people being put to work,
given other grants and taken out."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.models import Plan, Subscription
from app.modules.businesses.models import Business
from tests.pg.test_business_links import World
from tests.pg.test_business_members import _business, _manager, _staff

URL = "/api/v3/businesses"
STRONG = "Qo'ng'iroq-2026-yashil"


def _auth(user: User) -> dict[str, str]:
    token = tokens.issue(subject=str(user.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def _paid(world: World) -> None:
    """A paid plan: a free seat for every page the owner has switched on."""
    plan = Plan(price=100, max_adsets=10, llm_cost_limit_minor=0)
    world.db.add(plan)
    world.db.flush()
    world.db.add(
        Subscription(
            owner_id=world.owner.id,
            plan_id=plan.id,
            status="active",
            started_at=world.now - timedelta(days=1),
            expires_at=world.now + timedelta(days=29),
        )
    )
    world.db.commit()


def _new_login(name: str, roles: list[str], **more: object) -> dict[str, object]:
    return {
        "name": name,
        "email": f"{name.lower()}@example.com",
        "password": STRONG,
        "roles": roles,
        **more,
    }


def test_the_owner_s_businesses_with_what_each_advertises_from(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")

    listed = client.get(URL, headers=_auth(world.owner))

    assert listed.status_code == 200, listed.text
    cards = {card["id"]: card for card in listed.json()["businesses"]}
    assert set(cards) == {str(first.id), str(second.id)}
    card = cards[str(first.id)]
    assert card["name"] == "Biznes p1"
    assert card["access"] == {
        "is_owner": True,
        "roles": [],
        "is_rop": False,
        "reads_all_leads": True,
        "grants": [],
    }
    (network,) = card["networks"]
    assert (network["provider"], network["kind"], network["pair"]) == (
        "meta",
        "meta_pair",
        "p1:act_1",
    )
    assert network["page"]["external_id"] == "p1"
    assert network["ad_account"]["external_id"] == "act_1"


def test_one_business_for_its_owner_a_stranger_and_nobody(
    client: TestClient, db: Session
) -> None:
    world, other = World(db), World(db, "boshqa@example.com")
    business = _business(world)
    db.commit()

    shown = client.get(f"{URL}/{business.id}", headers=_auth(world.owner))
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert body["profile"]["name"] == "Biznes p1"
    assert body["profile"]["timezone"] == "Asia/Tashkent"
    assert body["members_count"] == 0

    hidden = client.get(f"{URL}/{business.id}", headers=_auth(other.owner))
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "unknown_business"
    assert client.get(f"{URL}/{business.id}").status_code == 401
    assert client.get(URL, headers=_auth(other.owner)).json() == {"businesses": []}


def test_what_the_member_form_offers(client: TestClient, db: Session) -> None:
    world = World(db)
    db.commit()

    body = client.get(f"{URL}/catalog", headers=_auth(world.owner)).json()

    roles = {role["key"]: role for role in body["roles"]}
    assert roles["targetolog"]["label"] == "Targetolog"
    assert roles["targetolog"]["may_be_rop"] is False
    assert roles["targetolog"]["grants"] == [
        {"area": "ads", "provider": "*", "level": "edit"}
    ]
    assert roles["sales"]["may_be_rop"] is True
    assert {(g["area"], g["provider"]) for g in roles["sales"]["grants"]} == {
        ("crm", "*"),
        ("crm", "other"),
    }
    assert [level["key"] for level in body["levels"]] == ["view", "edit"]
    assert body["other_source"]["key"] == "other"


def test_a_targetolog_is_added_with_a_login_and_reads_only_their_business(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)

    made = client.post(
        f"{URL}/{first.id}/members",
        json=_new_login("Ali", ["targetolog"]),
        headers=_auth(world.owner),
    )

    assert made.status_code == 201, made.text
    body = made.json()
    (member,) = body["members"]
    assert member["user"] == {
        "id": member["user"]["id"],
        "full_name": "Ali",
        "email": "ali@example.com",
    }
    assert (member["roles"], member["from_crm"]) == (["targetolog"], False)
    assert member["grants"] == [{"area": "ads", "provider": "meta", "level": "edit"}]
    assert body["seats"] == {"taken": 1, "capacity": 2, "free": 1}
    assert body["networks"] == ["meta"]

    ali = db.get(User, member["user"]["id"])
    assert ali is not None and ali.crm_owner_id == world.owner.id
    mine = client.get(URL, headers=_auth(ali)).json()["businesses"]
    assert [card["id"] for card in mine] == [str(first.id)]
    assert mine[0]["access"]["is_owner"] is False
    assert mine[0]["access"]["roles"] == ["targetolog"]
    shown = client.get(f"{URL}/{first.id}", headers=_auth(ali))
    assert shown.status_code == 200 and shown.json()["members_count"] is None
    assert client.get(f"{URL}/{second.id}", headers=_auth(ali)).status_code == 404
    refused = client.get(f"{URL}/{first.id}/members", headers=_auth(ali))
    assert (refused.status_code, refused.json()["code"]) == (403, "no_access")
    # The older API stays shut to a member's login, as before.
    assert client.get("/api/v1/business", headers=_auth(ali)).status_code == 403


def test_the_same_person_is_put_to_work_in_a_second_business(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)
    owner = _auth(world.owner)
    made = client.post(
        f"{URL}/{first.id}/members",
        json=_new_login("Ali", ["targetolog"]),
        headers=owner,
    ).json()
    person = made["members"][0]["user"]

    before = client.get(f"{URL}/{second.id}/members", headers=owner).json()
    assert before["members"] == [] and before["candidates"] == [person]

    added = client.post(
        f"{URL}/{second.id}/members",
        json={
            "user_id": person["id"],
            "roles": ["targetolog"],
            "grants": [{"area": "ads", "provider": "meta", "level": "view"}],
        },
        headers=owner,
    )

    assert added.status_code == 201, added.text
    body = added.json()
    assert body["candidates"] == []
    assert body["members"][0]["grants"] == [
        {"area": "ads", "provider": "meta", "level": "view"}
    ]
    assert body["seats"] == {"taken": 2, "capacity": 2, "free": 0}

    full = client.post(
        f"{URL}/{second.id}/members",
        json=_new_login("Vali", ["targetolog"]),
        headers=owner,
    )
    assert (full.status_code, full.json()["code"]) == (409, "no_seat")
    again = client.post(
        f"{URL}/{first.id}/members",
        json={"user_id": person["id"], "roles": ["targetolog"]},
        headers=owner,
    )
    assert again.status_code == 409


def test_what_the_owner_may_not_send(client: TestClient, db: Session) -> None:
    world, other = World(db), World(db, "boshqa@example.com")
    business = _business(world)
    _paid(world)
    stranger = _staff(other, "begona")
    db.commit()
    owner = _auth(world.owner)
    url = f"{URL}/{business.id}/members"

    def code(body: dict[str, object]) -> tuple[int, str]:
        answer = client.post(url, json=body, headers=owner)
        return answer.status_code, answer.json().get("code", "")

    assert code({"roles": ["targetolog"]}) == (400, "login_required")
    assert code({"user_id": str(stranger.id), "roles": ["targetolog"]}) == (
        400,
        "not_your_staff",
    )
    assert code(_new_login("Ali", ["targetolog"], is_rop=True)) == (
        400,
        "rop_needs_sales",
    )
    assert code(
        _new_login(
            "Ali",
            ["targetolog"],
            grants=[{"area": "ads", "provider": "google", "level": "edit"}],
        )
    ) == (400, "bad_grant")
    assert (
        client.post(url, json=_new_login("Ali", []), headers=owner).status_code == 422
    )
    assert client.get(url, headers=owner).json()["members"] == []
    assert db.query(User).filter(User.email == "ali@example.com").count() == 0


def test_a_manager_the_crm_added_is_shown_and_made_a_rop_here(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)
    _manager(world, business, "vali")
    owner = _auth(world.owner)
    url = f"{URL}/{business.id}/members"

    (member,) = client.get(url, headers=owner).json()["members"]
    assert (member["roles"], member["from_crm"], member["is_rop"]) == (
        ["sales"],
        True,
        False,
    )

    changed = client.patch(
        f"{url}/{member['id']}",
        json={"roles": ["sales", "targetolog"], "is_rop": True},
        headers=owner,
    )
    assert changed.status_code == 200, changed.text
    (member,) = changed.json()["members"]
    assert (member["roles"], member["is_rop"]) == (["sales", "targetolog"], True)
    assert {(g["area"], g["provider"]) for g in member["grants"]} == {
        ("ads", "meta"),
        ("crm", "meta"),
        ("crm", "other"),
    }

    # Without the sales role the person leaves the CRM and stays a targetolog.
    kept = client.patch(
        f"{url}/{member['id']}", json={"roles": ["targetolog"]}, headers=owner
    )
    assert kept.status_code == 200, kept.text
    (member,) = kept.json()["members"]
    assert (member["roles"], member["from_crm"], member["is_rop"]) == (
        ["targetolog"],
        False,
        False,
    )
    assert member["grants"] == [{"area": "ads", "provider": "meta", "level": "edit"}]


def test_a_member_taken_out_loses_the_business_at_once(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world)
    _paid(world)
    owner = _auth(world.owner)
    url = f"{URL}/{business.id}/members"
    member = client.post(
        url, json=_new_login("Ali", ["targetolog"]), headers=owner
    ).json()["members"][0]
    ali = db.get(User, member["user"]["id"])
    assert ali is not None

    trimmed = client.patch(
        f"{url}/{member['id']}",
        json={
            "roles": ["targetolog"],
            "grants": [{"area": "ads", "provider": "meta", "level": "view"}],
        },
        headers=owner,
    )
    assert trimmed.json()["members"][0]["grants"] == [
        {"area": "ads", "provider": "meta", "level": "view"}
    ]

    removed = client.delete(f"{url}/{member['id']}", headers=owner)

    assert removed.status_code == 200, removed.text
    assert removed.json()["members"] == []
    assert removed.json()["seats"]["taken"] == 0
    assert client.get(URL, headers=_auth(ali)).json() == {"businesses": []}
    assert client.get(f"{URL}/{business.id}", headers=_auth(ali)).status_code == 404
    missing = client.delete(f"{url}/{member['id']}", headers=owner)
    assert (missing.status_code, missing.json()["code"]) == (404, "unknown_member")
    assert db.get(Business, business.id) is not None
