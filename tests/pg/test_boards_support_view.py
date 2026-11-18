"""What the office reads about a Support ticket outside its card: the chat
list and the chat say whose it is; Hal qilindi and Yopildi show the last
week, a search finds the older."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.boards.constants import TicketReason
from app.modules.boards.schemas import BoardViewOut
from app.modules.boards.tickets import raise_ticket
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import URL, _detail, _live, _ticket
from tests.pg.test_supportchat import _send

CHAT = "/api/v1/office/support"


def test_the_chat_says_whose_ticket_it_is(client: TestClient, db: Session) -> None:
    _live(db)
    zarina = _staff(db, "zarina@view.test", Role.SUPPORT)
    olim = _staff(db, "olim@view.test", Role.SUPPORT)
    owner = _client(db, "chatty@view.test")
    _send(client, owner, body="Salom")
    rows = client.get(CHAT, headers=zarina).json()["rows"]
    assert [r["ticket"] for r in rows if r["customer"]["email"] == owner.email] == [
        None
    ]

    raise_ticket(db, owner_id=owner.id, reason=TicketReason.AI, ref="a", now=utcnow())
    db.commit()
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    mine = next(
        r
        for r in client.get(CHAT, headers=zarina).json()["rows"]
        if r["customer"]["email"] == owner.email
    )
    assert mine["ticket"]["id"] == taken.id and mine["ticket"]["mine"] is True
    assert (
        mine["ticket"]["column"] == "in_progress"
        and mine["ticket"]["column_label"] == "Ishlanmoqda"
    )
    assert mine["ticket"]["manager"]["email"] == "zarina@view.test"
    theirs = next(
        r
        for r in client.get(CHAT, headers=olim).json()["rows"]
        if r["customer"]["email"] == owner.email
    )
    assert theirs["ticket"]["mine"] is False

    screen = client.get(f"{CHAT}/{mine['id']}", headers=zarina).json()
    assert screen["ticket"]["id"] == taken.id and screen["ticket"]["closed"] is False


def test_done_columns_show_the_last_week(client: TestClient, db: Session) -> None:
    _live(db)
    boss = _staff(db, "boss@view.test", Role.OWNER)
    fresh = _client(db, "fresh@view.test")
    old = _client(db, "old@view.test")
    for person in (fresh, old):
        raise_ticket(
            db, owner_id=person.id, reason=TicketReason.SETUP, ref="a", now=utcnow()
        )
    db.commit()
    for person, days in ((fresh, 1), (old, 20)):
        ticket = _ticket(db, person)
        assert ticket is not None
        ticket.column_code = "resolved"
        ticket.closed_at = utcnow()
        ticket.column_since = utcnow() - timedelta(days=days)
        db.commit()

    view = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/support", headers=boss).json()
    )
    done = next(c for c in view.columns if c.code == "resolved")
    assert done.total == 1 and done.recent_days == 7
    assert [c.client.email for c in done.cards] == ["fresh@view.test"]
    assert next(c for c in view.columns if c.code == "new").recent_days is None

    found = BoardViewOut.model_validate(
        client.get(
            f"{URL}/boards/support", headers=boss, params={"q": "old@view"}
        ).json()
    )
    done = next(c for c in found.columns if c.code == "resolved")
    assert [c.client.email for c in done.cards] == [
        "old@view.test"
    ] and done.recent_days is None
