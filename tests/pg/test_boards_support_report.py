"""Support's daily report: clients talked to (chat or ticket work), tickets
taken and called solved, and the client's answer counted for whoever
pressed «Hal qilindi». A member reads their own line, the Owner everybody's,
Sales nothing."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.boards import confirm
from app.modules.boards.chat_hold import take_chat
from app.modules.boards.constants import TicketReason
from app.modules.boards.models import BoardCardEvent
from app.modules.boards.schemas import SupportReportOut
from app.modules.boards.tickets import raise_ticket
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.services import write_to_client
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import URL, _detail, _live, _ticket

REPORT = f"{URL}/boards/support/report"


def _raise(db: Session, email: str, *, minutes_ago: int) -> User:
    owner = _client(db, email)
    raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.SETUP,
        ref=f"{email}:1",
        now=utcnow() - timedelta(minutes=minutes_ago),
    )
    db.commit()
    return owner


def _user(db: Session, email: str) -> User:
    found = db.scalar(select(User).where(User.email == email))
    assert found is not None
    return found


def _solve(client: TestClient, head: dict[str, str], card_id: object) -> None:
    _detail(
        client.post(
            f"{URL}/cards/{card_id}/actions",
            headers=head,
            json={"action": "resolve", "note": "Hal qilindi"},
        )
    )


def _read(client: TestClient, head: dict[str, str], **query: str) -> SupportReportOut:
    answer = client.get(REPORT, headers=head, params=query)
    assert answer.status_code == 200, answer.text
    return SupportReportOut.model_validate(answer.json())


def test_each_member_by_day(client: TestClient, db: Session) -> None:
    _live(db)
    zarina = _staff(db, "zarina@rep.test", Role.SUPPORT)
    olim = _staff(db, "olim@rep.test", Role.SUPPORT)
    owner = _staff(db, "boss@rep.test", Role.OWNER)
    first = _raise(db, "first@shop.test", minutes_ago=30)
    second = _raise(db, "second@shop.test", minutes_ago=20)

    # Zarina takes the first, writes to the client and solves; the client says yes.
    _detail(client.post(f"{URL}/support/take", headers=zarina))
    member = _user(db, "zarina@rep.test")
    take_chat(db, client=first, user=member, now=utcnow())
    db.commit()
    for text in ("Salom", "Sozlab berdim"):
        write_to_client(
            db, client=first, sender=member, draft=Draft(body=text), now=utcnow()
        )
    ticket = _ticket(db, first)
    assert ticket is not None
    _solve(client, zarina, ticket.id)
    confirm.answer(db, owner_id=first.id, solved=True, via="test", now=utcnow())

    # Olim takes the second and solves it; the client says no.
    _detail(client.post(f"{URL}/support/take", headers=olim))
    other = _ticket(db, second)
    assert other is not None
    _solve(client, olim, other.id)
    confirm.answer(db, owner_id=second.id, solved=False, via="test", now=utcnow())

    everybody = _read(client, owner)
    rows = {m.email: m for m in everybody.members}
    assert set(rows) == {"zarina@rep.test", "olim@rep.test"}
    z = rows["zarina@rep.test"].total
    assert (z.talked, z.messages, z.taken, z.solved, z.confirmed, z.denied) == (
        1,
        2,
        1,
        1,
        1,
        0,
    )
    o = rows["olim@rep.test"].total
    assert (o.talked, o.messages, o.taken, o.solved, o.confirmed, o.denied) == (
        1,
        0,
        1,
        1,
        0,
        1,
    )
    assert everybody.total.talked == 2 and everybody.total.solved == 2
    today = localtime(utcnow()).date()
    assert [d.day for d in rows["zarina@rep.test"].days] == [today]

    # Zarina reads only her own line.
    mine = _read(client, zarina)
    assert [m.email for m in mine.members] == ["zarina@rep.test"]
    assert mine.total.solved == 1


def test_days_are_apart_and_the_period_is_kept(client: TestClient, db: Session) -> None:
    _live(db)
    zarina = _staff(db, "zarina2@rep.test", Role.SUPPORT)
    owner = _staff(db, "boss2@rep.test", Role.OWNER)
    first = _raise(db, "old@shop.test", minutes_ago=30)
    _detail(client.post(f"{URL}/support/take", headers=zarina))
    ticket = _ticket(db, first)
    assert ticket is not None
    # The take happened two days ago.
    db.execute(
        update(BoardCardEvent)
        .where(BoardCardEvent.card_id == ticket.id)
        .values(created_at=utcnow() - timedelta(days=2))
    )
    db.commit()
    _solve(client, zarina, ticket.id)

    today = localtime(utcnow()).date()
    week = _read(client, owner, date_from=str(today - timedelta(days=6)))
    row = next(m for m in week.members if m.email == "zarina2@rep.test")
    assert [d.day for d in row.days] == [today, today - timedelta(days=2)]
    assert [(d.taken, d.solved) for d in row.days] == [(0, 1), (1, 0)]
    # Taking a ticket is not talking to the client.
    assert [d.talked for d in row.days] == [1, 0]
    # Today alone: only the solve.
    one = next(m for m in _read(client, owner).members if m.email == "zarina2@rep.test")
    assert (one.total.taken, one.total.solved) == (0, 1)


def test_only_support_and_the_owner_read_it(client: TestClient, db: Session) -> None:
    _live(db)
    seller = _staff(db, "seller@rep.test", Role.SALES)
    assert client.get(REPORT, headers=seller).status_code == 404
    owner = _staff(db, "boss3@rep.test", Role.OWNER)
    today = localtime(utcnow()).date()
    bad = client.get(
        REPORT,
        headers=owner,
        params={"date_from": str(today), "date_to": str(today - timedelta(days=1))},
    )
    assert bad.status_code == 422
