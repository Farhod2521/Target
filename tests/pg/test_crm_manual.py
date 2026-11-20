"""A customer typed onto the board by hand: a card like any other inside the
CRM, and nothing at all outside it."""

import uuid
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.crm import selectors
from app.modules.crm.selectors.stats import stats
from app.modules.crm.services import collect_signals
from app.modules.integrations.selectors.audiences import _fillable
from app.modules.leads.models import Lead, LeadSignal
from core.metrics.sales import answers
from tests.pg.test_crm_http import CRM, _auth, _member, _owner, _running

LEADS = "/api/v1/leads"


def _add(
    client: TestClient,
    head: dict[str, str],
    name: str = "Vali",
    phone: str = "90 111 22 33",
    **more: Any,
) -> Any:
    return client.post(
        f"{CRM}/cards", headers=head, json={"name": name, "phone": phone, **more}
    )


def test_the_owner_types_a_customer_onto_the_board(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    _running(client, head)

    added = _add(client, head, note="Do'konga keldi")

    assert added.status_code == 201, added.text
    card = added.json()
    assert card["lead"]["manual"] is True
    assert card["lead"]["full_name"] == "Vali"
    assert card["lead"]["phone_e164"] == "+998901112233"
    assert card["lead"]["ad_external_id"] == ""
    assert card["last_note"] == "Do'konga keldi"
    board = client.get(CRM, headers=head).json()
    first = board["columns"][0]
    assert card["id"] in [c["id"] for c in first["cards"]]
    assert first["total"] == 4
    view = client.get(f"{CRM}/cards/{card['id']}", headers=head).json()
    kinds = [line["kind"] for line in view["history"]]
    assert "added" in kinds and "arrived" not in kinds
    assert view["source"] is None
    assert view["answers"] == []


def test_a_managers_own_customer_is_his_card_from_the_start(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    _running(client, head)
    _, manager = _member(client, head, "m1@example.com")
    new = "Yz4$kW8nRt2q"
    client.post(
        f"{CRM}/password", headers=manager, json={"password": new, "again": new}
    )

    added = _add(client, manager)

    assert added.status_code == 201, added.text
    assert added.json()["assignee"]["email"] == "m1@example.com"
    assert added.json()["taken_at"] is not None


def test_a_name_and_a_whole_telephone_are_asked_for(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    _running(client, head)

    refused = [
        _add(client, head, name="  "),
        _add(client, head, phone="12345"),
        _add(client, head, phone=""),
    ]

    assert [(r.status_code, r.json()["code"]) for r in refused] == [
        (400, "name_required"),
        (400, "phone_required"),
        (400, "phone_required"),
    ]
    assert db.scalar(select(Lead).where(Lead.provider == "manual")) is None


def test_one_telephone_is_one_open_card_and_a_sold_one_may_come_again(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    _running(client, head)
    first = _add(client, head).json()

    again = _add(client, head, name="Vali aka", phone="+998 90 111-22-33")

    assert again.status_code == 409
    assert again.json()["code"] == "phone_on_board"
    assert again.json()["hints"] == {"card_id": first["id"]}
    # An advert's lead with the same telephone is also that customer.
    known = _add(client, head, name="Lid", phone="+99890000000" + "1")
    assert known.json()["code"] == "phone_on_board"

    sold = client.post(
        f"{CRM}/cards/{first['id']}/win", headers=head, json={"amount": "100"}
    )
    assert sold.is_success, sold.text
    back = _add(client, head)

    assert back.status_code == 201, back.text
    assert back.json()["id"] != first["id"]
    assert back.json()["returned"] == 1


def test_no_customer_is_typed_onto_a_board_that_is_not_running(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))

    assert _add(client, head).json()["code"] == "not_running"


def test_outside_the_crm_the_customer_does_not_exist(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    _running(client, head)
    before = client.get(LEADS, headers=head).json()
    card = _add(client, head).json()
    sold = client.post(
        f"{CRM}/cards/{card['id']}/win", headers=head, json={"amount": "100"}
    )
    assert sold.is_success

    after = client.get(LEADS, headers=head)

    # Not on the Lidlar page, by list or by link.
    assert after.status_code == 200
    assert after.json() == before
    assert client.get(f"{LEADS}/{card['lead']['id']}", headers=head).status_code == 404
    # Not in a customer list sent to an ad network.
    telephones = [row[1] for row in db.execute(_fillable(owner=owner))]
    assert "+998901112233" not in telephones and len(telephones) == 3
    # And nothing of the sale is queued for Meta - while an advert's lead
    # sold the same way is.
    advert = db.scalar(select(Lead).where(Lead.provider != "manual"))
    assert advert is not None
    advert_card = next(
        c["id"]
        for column in client.get(CRM, headers=head).json()["columns"]
        for c in column["cards"]
        if c["lead"]["id"] == str(advert.id)
    )
    assert client.post(
        f"{CRM}/cards/{advert_card}/win", headers=head, json={"amount": "100"}
    ).is_success
    now = utcnow()
    collect_signals(
        db, owner=db.get(User, owner.id), until=now + timedelta(days=1), now=now
    )
    db.commit()
    told = set(db.scalars(select(LeadSignal.lead_id)))
    assert advert.id in told
    assert uuid.UUID(card["lead"]["id"]) not in told


def test_a_hand_typed_sale_stands_apart_from_the_advertising(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    advert_card = board["columns"][0]["cards"][0]["id"]
    client.post(f"{CRM}/cards/{advert_card}/win", headers=head, json={"amount": "50"})
    typed = _add(client, head).json()
    client.post(f"{CRM}/cards/{typed['id']}/win", headers=head, json={"amount": "200"})

    viewer = selectors.viewer_for(db, user=db.get(User, owner.id), wanted="")
    found = stats(db, viewer=viewer, period="7", now=utcnow())
    page = client.get(f"{CRM}/stats?period=7", headers=head).json()

    # What adverts brought: three leads, one sale of $50.
    assert (found.totals.leads, found.totals.won, found.totals.revenue_minor) == (
        3,
        1,
        5000,
    )
    # The hand-typed customer: one, sold for $200, with no spend of its own.
    assert (found.direct.leads, found.direct.won, found.direct.revenue_minor) == (
        1,
        1,
        20000,
    )
    assert answers(found.direct)["roas"].missing == "not_here"
    assert page["sales"]["totals"]["revenue"]["value"] == 5000
    assert page["sales"]["direct"]["revenue"]["value"] == 20000
    assert page["sales"]["direct"]["sales"]["value"] == 1
    # The board's own counts are of everybody on it.
    assert (page["totals"]["leads"], page["totals"]["won"]) == (4, 2)
    assert page["totals"]["revenue_minor"] == 25000
    assert sum(page["daily"]["leads"]) == 4
    assert [row["id"] for row in page["sales"]["ads"]] == ["ad_1"]


def test_many_cards_go_to_one_column_and_each_refusal_is_named(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    one, two, three = (c["id"] for c in board["columns"][0]["cards"])
    working = next(
        c["stage"]["id"] for c in board["columns"] if c["stage"]["kind"] == "open"
    )
    sold = next(
        c["stage"]["id"] for c in board["columns"] if c["stage"]["kind"] == "won"
    )
    missing = str(uuid.uuid4())

    moved = client.post(
        f"{CRM}/cards/bulk",
        headers=head,
        json={"ids": [one, two, one, missing], "action": "move", "to": working},
    )

    assert moved.status_code == 200, moved.text
    assert [c["id"] for c in moved.json()["done"]] == [one, two]
    assert {c["stage_id"] for c in moved.json()["done"]} == {working}
    assert [(r["id"], r["code"]) for r in moved.json()["refused"]] == [
        (missing, "unknown_card")
    ]
    # A column that asks for a sum is not entered by a bulk press.
    asked = client.post(
        f"{CRM}/cards/bulk",
        headers=head,
        json={"ids": [three], "action": "move", "to": sold},
    ).json()
    assert asked["done"] == []
    assert [r["code"] for r in asked["refused"]] == ["use_the_dialog"]
    columns = {
        c["stage"]["id"]: c["total"]
        for c in client.get(CRM, headers=head).json()["columns"]
    }
    assert columns[working] == 2
    # Each moved card has its step written, as a single move would.
    from app.modules.crm.models import CrmStageMove

    steps = db.scalars(
        select(CrmStageMove.to_kind).where(CrmStageMove.card_id == one)
    ).all()
    assert sorted(steps) == ["new", "open"]


def test_the_owner_hands_many_cards_to_a_manager_and_a_manager_cannot(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    one, two, three = (c["id"] for c in board["columns"][0]["cards"])
    member, manager = _member(client, head, "m1@example.com")
    new = "Yz4$kW8nRt2q"
    client.post(
        f"{CRM}/password", headers=manager, json={"password": new, "again": new}
    )
    seller = member["user"]["id"]

    handed = client.post(
        f"{CRM}/cards/bulk",
        headers=head,
        json={"ids": [one, two], "action": "assign", "to": seller},
    )

    assert handed.status_code == 200, handed.text
    assert {c["assignee"]["id"] for c in handed.json()["done"]} == {seller}
    assert handed.json()["refused"] == []
    # A manager hands nobody's cards out, and moves only his own.
    assert (
        client.post(
            f"{CRM}/cards/bulk",
            headers=manager,
            json={"ids": [three], "action": "assign", "to": seller},
        ).status_code
        == 404
    )
    working = next(
        c["stage"]["id"] for c in board["columns"] if c["stage"]["kind"] == "open"
    )
    his = client.post(
        f"{CRM}/cards/bulk",
        headers=manager,
        json={"ids": [one, three], "action": "move", "to": working},
    ).json()
    assert [c["id"] for c in his["done"]] == [one]
    assert [(r["id"], r["code"]) for r in his["refused"]] == [(three, "not_allowed")]


def test_a_bulk_press_carries_a_hundred_cards_at_most(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    _running(client, head)

    over = client.post(
        f"{CRM}/cards/bulk",
        headers=head,
        json={
            "ids": [str(uuid.uuid4()) for _ in range(101)],
            "action": "move",
            "to": "x",
        },
    )

    assert over.status_code == 422
