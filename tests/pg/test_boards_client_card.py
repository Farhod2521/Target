"""Somebody of Sales reads the whole card of a client of their own, from
the board's card; the clients list and every change stay closed to them."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.backoffice.schemas import CustomerCardOut
from app.modules.boards.schemas import MeOut
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client, _detail, _live, _sweep

URL = "/api/v2/office"
OFFICE = "/api/v1/office"


def _id(db: Session, email: str) -> str:
    return str(db.scalar(select(User.id).where(User.email == email)))


def test_a_sales_manager_reads_the_card_of_a_client_of_their_own(
    client: TestClient, db: Session
) -> None:
    _live(db)
    ali = _staff(db, "ali@office.test", Role.SALES)
    vali = _staff(db, "vali@office.test", Role.SALES)
    lead = _staff(db, "lead@office.test", Role.SALES_LEAD)
    help_ = _staff(db, "help@office.test", Role.SUPPORT)
    _client(db, "shop@shop.test")
    _client(db, "other@shop.test")
    _sweep(db)
    card = _detail(client.post(f"{URL}/sales/take", headers=ali))
    mine = str(card.client.id)
    other = next(
        found
        for found in (_id(db, "shop@shop.test"), _id(db, "other@shop.test"))
        if found != mine
    )

    me = MeOut.model_validate(client.get(f"{URL}/me", headers=ali).json())
    assert me.can.sales_client_card and not me.can.client_card

    # Their own client: the card, its adverts and its activity, to read.
    got = client.get(f"{OFFICE}/customers/{mine}", headers=ali)
    assert got.status_code == 200, got.text
    assert CustomerCardOut.model_validate(got.json()).reader == "sales"
    assert client.get(f"{OFFICE}/customers/{mine}/ads", headers=ali).status_code == 200
    assert (
        client.get(f"{OFFICE}/customers/{mine}/activity", headers=ali).status_code
        == 200
    )

    # Nobody's lead, and another manager's client: not theirs.
    assert client.get(f"{OFFICE}/customers/{other}", headers=ali).status_code == 404
    assert client.get(f"{OFFICE}/customers/{mine}", headers=vali).status_code == 404
    assert client.get(f"{OFFICE}/customers/{mine}/ads", headers=vali).status_code == 404

    # The lead reads the team's clients; Support reads as before.
    assert client.get(f"{OFFICE}/customers/{mine}", headers=lead).status_code == 200
    assert client.get(f"{OFFICE}/customers/{other}", headers=lead).status_code == 200
    whole = client.get(f"{OFFICE}/customers/{mine}", headers=help_)
    assert CustomerCardOut.model_validate(whole.json()).reader == "office"

    # The list, the other tabs and every change stay closed to Sales.
    assert client.get(f"{OFFICE}/customers", headers=ali).status_code == 404
    assert (
        client.get(f"{OFFICE}/customers/{mine}/surveys", headers=ali).status_code == 404
    )
    assert (
        client.post(
            f"{OFFICE}/customers/{mine}/days", headers=ali, json={"days": 3}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{OFFICE}/customers/{mine}/block", headers=ali, json={}
        ).status_code
        == 404
    )
