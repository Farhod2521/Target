"""The kinds of ticket each member of Support takes first: every kind by
default, set by the Owner and the superuser only; «Zayavka olish» gives a
member their own kinds first and any other once none of those waits; a
ticket with several reasons is a member's when any open one is theirs."""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.boards.constants import TicketReason
from app.modules.boards.models import SupportKind
from app.modules.boards.schemas import BoardViewOut, SupportKindsOut
from app.modules.boards.tickets import raise_ticket
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import URL, _detail, _live

KINDS = f"{URL}/boards/support/kinds"


def _raise(db: Session, email: str, *reasons: TicketReason, minutes_ago: int) -> User:
    owner = _client(db, email)
    for i, reason in enumerate(reasons):
        raise_ticket(
            db,
            owner_id=owner.id,
            reason=reason,
            ref=f"{email}:{i}",
            now=utcnow() - timedelta(minutes=minutes_ago),
        )
    db.commit()
    return owner


def _id(db: Session, email: str) -> str:
    member = db.scalar(select(User).where(User.email == email))
    assert member is not None
    return str(member.id)


def _set(client: TestClient, head: dict[str, str], member: str, kinds: list[str]):
    return client.put(f"{KINDS}/{member}", headers=head, json={"kinds": kinds})


def _take(client: TestClient, head: dict[str, str]) -> str:
    return _detail(client.post(f"{URL}/support/take", headers=head)).client.email


def test_every_member_takes_every_kind_until_the_owner_sets_some(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _staff(db, "aziz@team.test", Role.SUPPORT)
    owner = _staff(db, "boss@team.test", Role.OWNER)
    answer = client.get(KINDS, headers=owner)
    assert answer.status_code == 200, answer.text
    view = SupportKindsOut.model_validate(answer.json())
    assert [k.value for k in view.kinds] == [str(r) for r in TicketReason]
    assert view.kinds[0].label == "Sozlash tugamadi"
    aziz = next(m for m in view.members if m.email == "aziz@team.test")
    assert aziz.all and aziz.kinds == [str(r) for r in TicketReason]
    # The Owner is not on the team: not listed.
    assert all(m.email != "boss@team.test" for m in view.members)


def test_only_the_owner_and_the_superuser_read_and_set_kinds(
    client: TestClient, db: Session
) -> None:
    _live(db)
    aziz = _staff(db, "aziz2@team.test", Role.SUPPORT)
    member = _id(db, "aziz2@team.test")
    assert client.get(KINDS, headers=aziz).status_code == 404
    assert _set(client, aziz, member, ["setup"]).status_code == 404
    root = _staff(db, "root@team.test", superuser=True)
    answer = _set(client, root, member, ["setup", "ai"])
    assert answer.status_code == 200, answer.text
    assert answer.json()["kinds"] == ["setup", "ai"] and answer.json()["all"] is False


def test_bad_kinds_are_refused_and_every_kind_is_stored_as_none(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _staff(db, "aziz3@team.test", Role.SUPPORT)
    owner = _staff(db, "boss3@team.test", Role.OWNER)
    member = _id(db, "aziz3@team.test")
    assert _set(client, owner, member, []).status_code == 422
    assert _set(client, owner, member, ["nope"]).status_code == 422
    # Somebody not in Support has no kinds.
    _staff(db, "seller@team.test", Role.SALES)
    assert (
        _set(client, owner, _id(db, "seller@team.test"), ["setup"]).status_code == 404
    )
    assert _set(client, owner, str(uuid.uuid4()), ["setup"]).status_code == 404
    assert _set(client, owner, member, ["meta_error"]).status_code == 200
    every = _set(client, owner, member, [str(r) for r in TicketReason])
    assert every.status_code == 200 and every.json()["all"] is True
    rows = db.scalars(
        select(SupportKind).where(SupportKind.member_id == uuid.UUID(member))
    ).all()
    assert rows == []


def test_take_gives_own_kinds_first_then_any(client: TestClient, db: Session) -> None:
    _live(db)
    owner = _staff(db, "boss4@team.test", Role.OWNER)
    a = _staff(db, "a@team.test", Role.SUPPORT)
    b = _staff(db, "b@team.test", Role.SUPPORT)
    _set(client, owner, _id(db, "a@team.test"), ["setup"])
    _set(client, owner, _id(db, "b@team.test"), ["meta_error"])
    # Oldest first: an AI ticket, then a Meta error, then a setup one.
    _raise(db, "ai@shop.test", TicketReason.AI, minutes_ago=30)
    _raise(db, "meta@shop.test", TicketReason.META_ERROR, minutes_ago=20)
    _raise(db, "setup@shop.test", TicketReason.SETUP, minutes_ago=10)

    board = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/support", headers=a).json()
    )
    assert board.take is not None and (board.take.queue, board.take.own) == (3, 1)

    assert _take(client, a) == "setup@shop.test"
    assert _take(client, b) == "meta@shop.test"
    # None of A's kind waits: the oldest of any.
    assert _take(client, a) == "ai@shop.test"
    answer = client.post(f"{URL}/support/take", headers=b)
    assert answer.status_code == 409


def test_a_ticket_with_two_reasons_is_for_either_kind(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _staff(db, "boss5@team.test", Role.OWNER)
    c = _staff(db, "c@team.test", Role.SUPPORT)
    _set(client, owner, _id(db, "c@team.test"), ["ai"])
    _raise(db, "plain@shop.test", TicketReason.SETUP, minutes_ago=30)
    _raise(db, "both@shop.test", TicketReason.SETUP, TicketReason.AI, minutes_ago=5)
    assert _take(client, c) == "both@shop.test"


def test_a_solved_reason_does_not_count_for_the_kind(
    client: TestClient, db: Session
) -> None:
    _live(db)
    owner = _staff(db, "boss6@team.test", Role.OWNER)
    d = _staff(db, "d@team.test", Role.SUPPORT)
    e = _staff(db, "e@team.test", Role.SUPPORT)
    _set(client, owner, _id(db, "e@team.test"), ["ai"])
    _raise(db, "old@shop.test", TicketReason.SETUP, minutes_ago=60)
    _raise(db, "back@shop.test", TicketReason.AI, minutes_ago=50)
    # D takes and solves the AI ticket; it comes back about setup.
    assert _take(client, d) == "old@shop.test"
    assert _take(client, d) == "back@shop.test"
    from tests.pg.test_boards_support import _ticket

    back = _ticket(db, db.scalar(select(User).where(User.email == "back@shop.test")))
    assert back is not None
    client.post(
        f"{URL}/cards/{back.id}/actions",
        headers=d,
        json={"action": "resolve", "note": "Tushuntirildi"},
    )
    raise_ticket(
        db,
        owner_id=back.owner_id,
        reason=TicketReason.SETUP,
        ref="back:setup",
        now=utcnow(),
    )
    db.commit()
    _raise(db, "ai2@shop.test", TicketReason.AI, minutes_ago=0)
    # The returned ticket is older but its open reason is setup, not AI.
    assert _take(client, e) == "ai2@shop.test"
