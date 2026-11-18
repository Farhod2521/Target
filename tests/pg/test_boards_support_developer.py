"""«Dasturchiga berish» keeps a fault for the Developers; settling it closes
the ticket and tells its person. «Bog'lanib bo'lmadi» with a time to call
again comes back when the time comes."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.audit.models import ErrorEvent
from app.modules.backoffice.constants import Role
from app.modules.boards import notices, triggers
from app.modules.boards.constants import TicketReason
from app.modules.boards.models import BoardCardEvent, ContactReason
from app.modules.boards.tickets import raise_ticket
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import URL, _detail, _live, _ticket

FAULTS = "/api/v1/office/faults"


def _taken(client: TestClient, db: Session, email: str, member: dict[str, str]):
    owner = _client(db, email)
    raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.META_ERROR,
        ref=f"{email}:1",
        now=utcnow(),
        detail="Reklama ishga tushmadi",
        extra={"raw": "Error validating access token | code 190/460"},
    )
    db.commit()
    taken = _detail(client.post(f"{URL}/support/take", headers=member))
    return owner, taken


def _press(client: TestClient, head: dict[str, str], card_id: str, **body: object):
    answer = client.post(f"{URL}/cards/{card_id}/actions", headers=head, json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_handed_over_fixed_closes_the_ticket(client: TestClient, db: Session) -> None:
    _live(db)
    zarina = _staff(db, "zarina@dev.test", Role.SUPPORT)
    engineer = _staff(db, "eng@dev.test", Role.ENGINEER)
    owner, taken = _taken(client, db, "shop@dev.test", zarina)

    _press(
        client, zarina, taken.id, action="to_developer", note="Token yangilanmayapti"
    )
    fault = db.scalar(select(ErrorEvent).where(ErrorEvent.path == f"ticket:{taken.id}"))
    assert fault is not None and fault.resolved_at is None
    assert (
        "Token yangilanmayapti" in fault.message
        and "Reklama ishga tushmadi" in fault.message
    )
    assert fault.context["problems"][0]["meta"].startswith("Error validating")
    line = db.scalar(select(BoardCardEvent).where(BoardCardEvent.kind == "developer"))
    assert line is not None and fault.reference in line.body

    # The Developer page lists it as Support's ticket.
    listed = client.get(FAULTS, headers=engineer).json()
    assert [f["title"] for f in listed if f["ref"] == fault.reference] == [
        "Support zayavkasi — Support dasturchiga berdi"
    ]
    done = client.post(f"{FAULTS}/{fault.reference}/settle", headers=engineer)
    assert done.status_code == 204, done.text

    ticket = _ticket(db, owner)
    assert ticket is not None
    assert ticket.column_code == "resolved" and ticket.closed_at is not None
    assert all(r.get("solved_at") for r in ticket.reasons)
    assert ticket.reasons[0]["solved_by"] == "eng@dev.test"
    # Its person hears of it (the staff bot is off here: marked, nothing sent).
    fixed = db.scalar(select(BoardCardEvent).where(BoardCardEvent.kind == "dev_fixed"))
    assert fixed is not None and fixed.kind in notices.NOTICE_KINDS


def test_a_ticket_taken_back_is_only_told(client: TestClient, db: Session) -> None:
    _live(db)
    zarina = _staff(db, "zarina2@dev.test", Role.SUPPORT)
    engineer = _staff(db, "eng2@dev.test", Role.ENGINEER)
    owner, taken = _taken(client, db, "back@dev.test", zarina)
    _press(client, zarina, taken.id, action="to_developer", note="Ko'ring")
    _press(client, zarina, taken.id, action="start")
    fault = db.scalar(select(ErrorEvent).where(ErrorEvent.path == f"ticket:{taken.id}"))
    assert fault is not None
    client.post(f"{FAULTS}/{fault.reference}/settle", headers=engineer)
    ticket = _ticket(db, owner)
    assert ticket is not None and ticket.column_code == "in_progress"
    assert db.scalar(select(BoardCardEvent).where(BoardCardEvent.kind == "dev_fixed"))


def test_unreachable_comes_back_at_the_time_to_call(
    client: TestClient, db: Session
) -> None:
    _live(db)
    zarina = _staff(db, "zarina3@dev.test", Role.SUPPORT)
    owner, taken = _taken(client, db, "far@dev.test", zarina)
    reason = ContactReason(name="Telefon o'chiq", position=1)
    db.add(reason)
    db.commit()
    later = utcnow() + timedelta(hours=3)
    out = _press(
        client,
        zarina,
        taken.id,
        action="unreachable",
        reason=str(reason.id),
        due_at=later.isoformat(),
    )
    assert out["column"] == "unreachable" and out["due_at"] is not None
    triggers.wait_over(db, now=utcnow() + timedelta(hours=1))
    ticket = _ticket(db, owner)
    assert ticket is not None and ticket.column_code == "unreachable"
    triggers.wait_over(db, now=later + timedelta(minutes=1))
    ticket = _ticket(db, owner)
    assert ticket is not None and ticket.column_code == "in_progress"
    assert ticket.manager_id is not None and ticket.due_at is None
    back = db.scalar(select(BoardCardEvent).where(BoardCardEvent.kind == "call_again"))
    assert back is not None

    # Without a time it stays until the client writes, as before.
    _press(client, zarina, taken.id, action="unreachable", reason=str(reason.id))
    triggers.wait_over(db, now=utcnow() + timedelta(days=30))
    ticket = _ticket(db, owner)
    assert ticket is not None and ticket.column_code == "unreachable"
