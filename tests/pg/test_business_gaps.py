"""What the cabinet's new screens asked of the business API, against
PostgreSQL: who signed in, a pair with no profile of its own, a member's
audiences and pixels, a member's password set by the owner, and what
happens to a login when its last work is taken away."""

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount, CustomAudience, PixelAccount
from tests.pg.test_business_links import World
from tests.pg.test_business_members import _business
from tests.pg.test_business_networks import _on
from tests.pg.test_business_v3 import STRONG, URL, _auth, _new_login, _paid


def _member(  # type: ignore[no-untyped-def]
    client: TestClient, world: World, business: Business, name: str = "Ali", **more
) -> tuple[User, str]:
    made = client.post(
        f"{URL}/{business.id}/members",
        json=_new_login(name, ["targetolog"], **more),
        headers=_auth(world.owner),
    )
    assert made.status_code == 201, made.text
    row = next(
        one for one in made.json()["members"] if one["user"]["full_name"] == name
    )
    user = world.db.get(User, row["user"]["id"])
    assert user is not None
    return user, row["id"]


def _account(db: Session, external_id: str) -> AdAccount:
    return db.query(AdAccount).filter_by(external_id=external_id).one()


def _audience(world: World, account: AdAccount, name: str) -> CustomAudience:
    row = CustomAudience(
        owner_id=world.owner.id,
        provider=PROVIDER,
        external_id=f"aud-{name}",
        ad_account_id=account.id,
        name=name,
        is_ready=True,
    )
    world.db.add(row)
    world.db.flush()
    return row


def test_the_account_says_whether_an_owner_or_a_member_signed_in(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world, "p1")
    _paid(world)
    ali, _ = _member(client, world, business)

    owner = client.get("/api/v1/account", headers=_auth(world.owner)).json()
    member = client.get("/api/v1/account", headers=_auth(ali)).json()

    assert (owner["kind"], owner["crm_owner_id"]) == ("owner", None)
    assert (member["kind"], member["crm_owner_id"]) == ("member", str(world.owner.id))


def test_a_pair_whose_page_has_no_profile_is_a_business_too(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    _business(world, "p1")
    bare = world.page("p2", profile=False)
    world.pair(bare, world.account("act_2"))
    db.commit()

    listed = client.get(URL, headers=_auth(world.owner)).json()["businesses"]

    assert sorted(one["networks"][0]["pair"] for one in listed) == [
        "p1:act_1",
        "p2:act_2",
    ]


def test_a_targetolog_reads_and_makes_the_business_s_audiences_only(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    ours = _audience(world, _account(db, "act_1"), "Bizniki")
    theirs = _audience(world, _account(db, "act_2"), "Boshqa biznesniki")
    _paid(world)
    ali, member_id = _member(client, world, first)
    rows = "/api/v1/connections/audiences/rows"

    read = client.get(rows, headers=_on(ali, first))

    assert read.status_code == 200, read.text
    assert [one["name"] for one in read.json()["audiences"]] == ["Bizniki"]
    assert len(read.json()["seeds"]) == 1
    # The owner naming a business reads that business's too; naming none, all.
    named = client.get(rows, headers=_on(world.owner, second)).json()
    assert [one["name"] for one in named["audiences"]] == ["Boshqa biznesniki"]
    # Another business's audience is not there to be deleted.
    gone = client.delete(
        f"/api/v1/connections/audiences/{theirs.id}", headers=_on(ali, first)
    )
    assert gone.status_code == 404, gone.text
    # The rest of the owner's cabinet stays shut, with and without a business.
    for path in ("/api/v1/connections", "/api/v1/connections/cabinet"):
        assert client.get(path, headers=_on(ali, first)).status_code == 403
    assert client.get(rows, headers=_auth(ali)).status_code == 403
    assert client.get(rows, headers=_on(ali, second)).status_code == 404

    # «Ko'rish» reads and changes nothing.
    client.patch(
        f"{URL}/{first.id}/members/{member_id}",
        json={
            "roles": ["targetolog"],
            "grants": [{"area": "ads", "provider": "meta", "level": "view"}],
        },
        headers=_auth(world.owner),
    )
    assert client.get(rows, headers=_on(ali, first)).status_code == 200
    refused = client.delete(
        f"/api/v1/connections/audiences/{ours.id}", headers=_on(ali, first)
    )
    assert (refused.status_code, refused.json()["code"]) == (403, "no_access")


def test_the_pixels_of_the_business_s_account(client: TestClient, db: Session) -> None:
    world, other = World(db), World(db, "boshqa@example.com")
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    for account_id, name, active in (
        ("act_1", "Asosiy", True),
        ("act_1", "Eski", False),
        ("act_2", "Boshqa", True),
    ):
        db.add(
            PixelAccount(
                owner_id=world.owner.id,
                provider=PROVIDER,
                external_id=f"px-{name}",
                connection_id=world.connection.id,
                ad_account_id=_account(db, account_id).id,
                name=name,
                is_active=active,
            )
        )
    _paid(world)
    ali, _ = _member(client, world, first)

    read = client.get(f"{URL}/{first.id}/pixels", headers=_auth(ali))

    assert read.status_code == 200, read.text
    assert [(one["name"], one["is_active"]) for one in read.json()["pixels"]] == [
        ("Asosiy", True),
        ("Eski", False),
    ]
    owner = client.get(f"{URL}/{second.id}/pixels", headers=_auth(world.owner))
    assert [one["name"] for one in owner.json()["pixels"]] == ["Boshqa"]
    # Not their business, and not anybody's who is outside it.
    assert (
        client.get(f"{URL}/{second.id}/pixels", headers=_auth(ali)).status_code == 404
    )
    stranger = client.get(f"{URL}/{first.id}/pixels", headers=_auth(other.owner))
    assert stranger.status_code == 404


def test_the_owner_sets_a_member_s_password(client: TestClient, db: Session) -> None:
    world = World(db)
    business = _business(world, "p1")
    _paid(world)
    ali, member_id = _member(client, world, business)
    url = f"{URL}/{business.id}/members/{member_id}/password"
    new = "Yangi-parol-2026-qizil"

    weak = client.post(url, json={"password": "12345678"}, headers=_auth(world.owner))
    assert weak.status_code == 400, weak.text
    not_owner = client.post(url, json={"password": new}, headers=_auth(ali))
    assert (not_owner.status_code, not_owner.json()["code"]) == (403, "no_access")

    done = client.post(url, json={"password": new}, headers=_auth(world.owner))

    assert done.status_code == 200, done.text
    login = "/api/v1/auth/login"
    old = client.post(login, json={"email": ali.email, "password": STRONG})
    fresh = client.post(login, json={"email": ali.email, "password": new})
    assert (old.status_code, fresh.status_code) == (401, 200), (old.text, fresh.text)
    history = client.get(
        f"{URL}/{business.id}/history", headers=_auth(world.owner)
    ).json()["items"]
    assert history[0]["kind"] == "member_password"
    assert history[0]["member"]["full_name"] == "Ali"


def test_a_login_is_closed_with_its_last_work(client: TestClient, db: Session) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    _paid(world)
    ali, in_first = _member(client, world, first)
    ali_id = ali.id

    def closes(business: Business) -> bool:
        members = client.get(
            f"{URL}/{business.id}/members", headers=_auth(world.owner)
        ).json()["members"]
        return bool(members[0]["login_closes"])

    assert closes(first) is True
    also = client.post(
        f"{URL}/{second.id}/members",
        json={"user_id": str(ali_id), "roles": ["targetolog"]},
        headers=_auth(world.owner),
    )
    assert also.status_code == 201, also.text
    in_second = also.json()["members"][0]["id"]
    assert (closes(first), closes(second)) == (False, False)

    # Out of one business, still at work in the other: the login stays.
    left = client.delete(
        f"{URL}/{first.id}/members/{in_first}", headers=_auth(world.owner)
    )
    assert left.status_code == 200, left.text
    assert client.get(URL, headers=_auth(ali)).status_code == 200
    assert closes(second) is True

    # Out of the last one: the login is closed, and is no candidate again.
    last = client.delete(
        f"{URL}/{second.id}/members/{in_second}", headers=_auth(world.owner)
    )
    assert last.status_code == 200, last.text
    assert last.json()["members"] == [] and last.json()["candidates"] == []
    db.expire_all()
    holder = db.get(User, ali_id)
    assert holder is None or holder.is_active is False
    token = _auth(User(id=ali_id))
    assert client.get(URL, headers=token).status_code == 401
