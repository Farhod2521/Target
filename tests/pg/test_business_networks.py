"""Another network tied to a business, against PostgreSQL: one account of a
network per business, the members' grants that follow, the request that
names the business answered about that account, and the leads it brings."""

import pytest
from fastapi.testclient import TestClient
from googleadskit import PROVIDER as GOOGLE
from sqlalchemy.orm import Session

from app.common.acting import Acting, override
from app.common.config import settings
from app.common.crypto import fingerprint
from app.modules.accounts.models import User
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.integrations.selectors.google import (
    current_google_account,
    subscribed_google_accounts,
)
from app.modules.leads.models import Lead
from tests.pg.test_business_links import World
from tests.pg.test_business_members import _business
from tests.pg.test_business_v3 import URL, _auth, _new_login, _paid


def _google(world: World, external_id: str, *, current: bool = False) -> AdAccount:
    db = world.db
    connection = (
        db.query(ProviderConnection)
        .filter_by(owner_id=world.owner.id, provider=GOOGLE)
        .one_or_none()
    )
    if connection is None:
        connection = ProviderConnection(
            owner_id=world.owner.id,
            provider=GOOGLE,
            external_user_id=f"g-{world.owner.email}",
            token_encrypted=b"x",
            token_fingerprint=fingerprint(f"g-{world.owner.email}"),
        )
        db.add(connection)
        db.flush()
    row = AdAccount(
        owner_id=world.owner.id,
        provider=GOOGLE,
        external_id=external_id,
        connection_id=connection.id,
        name=f"Google {external_id}",
        currency="USD",
        timezone="Asia/Tashkent",
        may_advertise=True,
        is_active=True,
        is_current=current,
    )
    db.add(row)
    db.flush()
    return row


def _bind(client: TestClient, owner: User, business: Business, account: AdAccount):  # type: ignore[no-untyped-def]
    return client.post(
        f"{URL}/{business.id}/networks",
        json={"ad_account_id": str(account.id)},
        headers=_auth(owner),
    )


def _on(user: User, business: Business | None = None) -> dict[str, str]:
    headers = _auth(user)
    if business is not None:
        headers["X-Business"] = str(business.id)
    return headers


def _grants(client: TestClient, world: World, business: Business) -> dict[str, list]:  # type: ignore[type-arg]
    members = client.get(f"{URL}/{business.id}/members", headers=_auth(world.owner))
    return {
        one["user"]["full_name"]: sorted(
            (grant["area"], grant["provider"], grant["level"])
            for grant in one["grants"]
        )
        for one in members.json()["members"]
    }


def test_the_owner_ties_a_google_account_to_one_business(
    client: TestClient, db: Session
) -> None:
    world, other = World(db), World(db, "boshqa@example.com")
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    one, two = _google(world, "111", current=True), _google(world, "222")
    foreign = _google(other, "333")
    meta = db.query(AdAccount).filter_by(external_id="act_1").one()
    db.commit()

    offered = client.get(f"{URL}/{first.id}/networks", headers=_auth(world.owner))
    assert offered.status_code == 200, offered.text
    assert [row["provider"] for row in offered.json()["networks"]] == ["meta"]
    assert {row["external_id"] for row in offered.json()["available"]} == {"111", "222"}

    bound = _bind(client, world.owner, first, one)

    assert bound.status_code == 201, bound.text
    body = bound.json()
    assert [row["provider"] for row in body["networks"]] == ["google", "meta"]
    google = body["networks"][0]
    assert (google["kind"], google["pair"], google["page"]) == (
        "ad_account",
        "111",
        None,
    )
    assert google["ad_account"]["name"] == "Google 111"
    # One account of a network: nothing more of Google is offered here.
    assert body["available"] == []

    again = _bind(client, world.owner, first, two)
    assert (again.status_code, again.json()["code"]) == (409, "network_taken")
    elsewhere = _bind(client, world.owner, second, one)
    assert (elsewhere.status_code, elsewhere.json()["code"]) == (409, "account_bound")
    not_meta = _bind(client, world.owner, first, meta)
    assert not_meta.json()["code"] == "meta_is_pair"
    not_theirs = _bind(client, world.owner, second, foreign)
    assert (not_theirs.status_code, not_theirs.json()["code"]) == (
        404,
        "unknown_account",
    )

    # The other business is offered the account that is still free.
    left = client.get(f"{URL}/{second.id}/networks", headers=_auth(world.owner))
    assert [row["external_id"] for row in left.json()["available"]] == ["222"]
    card = client.get(f"{URL}/{first.id}", headers=_auth(world.owner)).json()
    assert [row["provider"] for row in card["networks"]] == ["google", "meta"]


def test_members_get_on_the_new_network_what_they_hold_on_the_others(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.billing.selectors import seats as bought

    # A page's free seat holds one person: the others sit in bought seats.
    monkeypatch.setattr(bought, "paid_seats", lambda *_, **__: 10)
    world = World(db)
    business = _business(world, "p1")
    account = _google(world, "111")
    _paid(world)
    db.commit()
    for name, roles, more in (
        ("Ali", ["targetolog"], {}),
        (
            "Bobur",
            ["targetolog"],
            {"grants": [{"area": "ads", "provider": "meta", "level": "view"}]},
        ),
        ("Vali", ["sales"], {}),
    ):
        made = client.post(
            f"{URL}/{business.id}/members",
            json=_new_login(name, roles, **more),
            headers=_auth(world.owner),
        )
        assert made.status_code == 201, made.text

    assert _bind(client, world.owner, business, account).status_code == 201

    held = _grants(client, world, business)
    assert held["Ali"] == [("ads", "google", "edit"), ("ads", "meta", "edit")]
    assert held["Bobur"] == [("ads", "google", "view"), ("ads", "meta", "view")]
    assert held["Vali"] == [
        ("crm", "google", "edit"),
        ("crm", "meta", "edit"),
        ("crm", "other", "edit"),
    ]

    untied = client.delete(
        f"{URL}/{business.id}/networks/google", headers=_auth(world.owner)
    )

    assert untied.status_code == 200, untied.text
    assert [row["provider"] for row in untied.json()["networks"]] == ["meta"]
    assert [row["external_id"] for row in untied.json()["available"]] == ["111"]
    held = _grants(client, world, business)
    assert held["Ali"] == [("ads", "meta", "edit")]
    assert held["Vali"] == [("crm", "meta", "edit"), ("crm", "other", "edit")]
    gone = client.delete(
        f"{URL}/{business.id}/networks/google", headers=_auth(world.owner)
    )
    assert (gone.status_code, gone.json()["code"]) == (404, "unknown_network")
    meta = client.delete(
        f"{URL}/{business.id}/networks/meta", headers=_auth(world.owner)
    )
    assert meta.json()["code"] == "meta_is_pair"


def test_the_history_says_who_was_given_what_and_when(
    client: TestClient, db: Session
) -> None:
    world = World(db)
    business = _business(world, "p1")
    account = _google(world, "111")
    _paid(world)
    db.commit()
    made = client.post(
        f"{URL}/{business.id}/members",
        json=_new_login("Ali", ["targetolog"]),
        headers=_auth(world.owner),
    )
    member_id = made.json()["members"][0]["id"]
    client.patch(
        f"{URL}/{business.id}/members/{member_id}",
        json={
            "roles": ["targetolog"],
            "grants": [{"area": "ads", "provider": "meta", "level": "view"}],
        },
        headers=_auth(world.owner),
    )
    # The same again changes nothing, and writes nothing.
    client.patch(
        f"{URL}/{business.id}/members/{member_id}",
        json={
            "roles": ["targetolog"],
            "grants": [{"area": "ads", "provider": "meta", "level": "view"}],
        },
        headers=_auth(world.owner),
    )
    _bind(client, world.owner, business, account)
    client.delete(
        f"{URL}/{business.id}/members/{member_id}", headers=_auth(world.owner)
    )

    read = client.get(f"{URL}/{business.id}/history", headers=_auth(world.owner))

    assert read.status_code == 200, read.text
    items = read.json()["items"]
    assert [item["kind"] for item in items] == [
        "member_removed",
        "network_bound",
        "member_changed",
        "member_added",
    ]
    changed = items[2]
    assert changed["member"]["full_name"] == "Ali"
    assert changed["before"]["grants"] == [
        {"area": "ads", "provider": "meta", "level": "edit"}
    ]
    assert changed["after"]["grants"] == [
        {"area": "ads", "provider": "meta", "level": "view"}
    ]
    assert (items[1]["provider"], items[1]["account_name"]) == ("google", "Google 111")
    assert items[1]["label"] == "Biznesga tarmoq ulandi"
    # The history is the owner's to read; the login taken out of its last
    # business is closed.
    ali = User(id=made.json()["members"][0]["user"]["id"])
    assert (
        client.get(f"{URL}/{business.id}/history", headers=_auth(ali)).status_code
        == 401
    )


def test_a_request_that_names_a_business_is_answered_about_its_google_account(
    db: Session,
) -> None:
    world = World(db)
    first, second = _business(world, "p1"), _business(world, "p2", "act_2")
    one, two = _google(world, "111", current=True), _google(world, "222")
    from app.modules.businesses.services import networks

    networks.bind(db, business=second, account_id=two.id)
    db.commit()

    def held(business: Business, account: AdAccount | None) -> Acting:
        return Acting(
            business_id=business.id,
            owner_id=world.owner.id,
            actor_id=world.owner.id,
            page_id=None,
            ad_account_id=None,
            accounts=((GOOGLE, account.id),) if account is not None else (),
        )

    # The cabinet, with no business named, is where it was.
    assert current_google_account(db, owner=world.owner) == one
    assert len(subscribed_google_accounts(db, owner=world.owner)) == 2
    with override(held(second, two)):
        assert current_google_account(db, owner=world.owner) == two
        assert subscribed_google_accounts(db, owner=world.owner) == [two]
    # A business with no Google account has none, whatever the cabinet is on.
    with override(held(first, None)):
        assert current_google_account(db, owner=world.owner) is None


def test_a_targetolog_opens_google_only_with_a_grant_over_it(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", "x")
    monkeypatch.setattr(settings, "google_ads_enabled", True)
    world = World(db)
    business = _business(world, "p1")
    account = _google(world, "111", current=True)
    _paid(world)
    db.commit()
    made = client.post(
        f"{URL}/{business.id}/members",
        json=_new_login("Ali", ["targetolog"]),
        headers=_auth(world.owner),
    )
    assert made.status_code == 201, made.text
    ali = db.get(User, made.json()["members"][0]["user"]["id"])
    assert ali is not None
    screen = "/api/v1/google/screen"

    # Google is not the business's yet: the member holds nothing over it.
    refused = client.get(screen, headers=_on(ali, business))
    assert (refused.status_code, refused.json()["code"]) == (403, "no_access")

    assert _bind(client, world.owner, business, account).status_code == 201
    opened = client.get(screen, headers=_on(ali, business))
    assert opened.status_code == 200, opened.text

    # Which account the cabinet stands on is the owner's to choose.
    moved = client.post(
        "/api/v1/google/account", json={"id": "111"}, headers=_on(ali, business)
    )
    assert (moved.status_code, moved.json()["code"]) == (403, "no_access")

    # Left with Meta alone, Google is shut again, and a Google draft too.
    member_id = made.json()["members"][0]["id"]
    client.patch(
        f"{URL}/{business.id}/members/{member_id}",
        json={
            "roles": ["targetolog"],
            "grants": [{"area": "ads", "provider": "meta", "level": "edit"}],
        },
        headers=_auth(world.owner),
    )
    assert client.get(screen, headers=_on(ali, business)).status_code == 403
    draft = client.post(
        "/api/v1/launch/drafts", json={"flow": "google"}, headers=_on(ali, business)
    )
    assert (draft.status_code, draft.json()["code"]) == (403, "no_access")


def test_a_lead_of_the_tied_account_is_the_business_s(db: Session) -> None:
    from app.modules.businesses.services import networks

    world = World(db)
    business = _business(world, "p1")
    account = _google(world, "111")
    db.commit()

    def lead(ident: str, campaign: str) -> Lead:
        row = Lead(
            owner_id=world.owner.id,
            provider=GOOGLE,
            leadgen_id=ident,
            campaign_external_id=campaign,
            submitted_at=world.now,
            received_at=world.now,
        )
        db.add(row)
        db.flush()
        return row

    early = lead("g1", "customers/111/campaigns/5")
    stranger = lead("g2", "customers/999/campaigns/5")
    assert early.business_id is None

    networks.bind(db, business=business, account_id=account.id)
    db.commit()
    late = lead("g3", "customers/111/campaigns/7")
    other = lead("g4", "customers/999/campaigns/7")
    db.commit()

    db.refresh(early)
    assert early.business_id == business.id
    assert late.business_id == business.id
    assert stranger.business_id is None and other.business_id is None
