"""A fully closed Support ticket (Hal qilindi, Yopildi) is nobody's: a new
fact opens a new round in Yangi for whoever takes it next, the client's own
refused press opens nothing, and a member may open it by hand for
themselves. A ticket waiting for the client's word opens a new round in
the queue too."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.audit.models import ActionLog
from app.modules.backoffice.constants import Role
from app.modules.boards import triggers
from app.modules.boards.constants import TicketReason
from app.modules.boards.models import BoardCardEvent
from app.modules.boards.tickets import raise_ticket
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import URL, _bought, _detail, _live, _ticket


def _solved_by(client: TestClient, db: Session, email: str, column: str):
    """A client whose ticket a member took and that now stands in ``column``."""
    _live(db)
    owner = _client(db, email)
    _bought(db, owner, minutes_ago=61)
    triggers.sweep_support(db, now=utcnow())
    zarina = _staff(db, f"zarina-{email}", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=zarina))
    ticket = _ticket(db, owner)
    assert ticket is not None and str(ticket.id) == taken.id
    ticket.column_code = column
    if column == "closed":
        ticket.closed_at = utcnow()
    db.commit()
    return owner, zarina, ticket


@pytest.mark.parametrize("column", ["resolved", "closed"])
def test_a_new_fact_on_a_closed_ticket_goes_to_the_queue(
    client: TestClient, db: Session, column: str
) -> None:
    owner, zarina, ticket = _solved_by(client, db, f"{column}@shop.test", column)
    assert raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.META_ERROR,
        ref=f"launch:{column}",
        now=utcnow(),
        detail="Reklama ishga tushmadi",
    )
    db.commit()
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert ticket.column_code == "new" and ticket.manager_id is None
    assert ticket.closed_at is None
    # Gone from the member's board; in the queue for «Zayavka olish».
    assert client.get(f"{URL}/cards/{ticket.id}", headers=zarina).status_code == 404


def test_a_ticket_waiting_for_the_client_opens_a_new_round_in_the_queue(
    client: TestClient, db: Session
) -> None:
    owner, zarina, ticket = _solved_by(client, db, "asked@shop.test", "in_progress")
    pressed = _detail(
        client.post(
            f"{URL}/cards/{ticket.id}/actions",
            headers=zarina,
            json={"action": "resolve", "note": "Sozlab berildi"},
        )
    )
    assert pressed.column == "confirming"
    raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.META_ERROR,
        ref="launch:x",
        now=utcnow(),
    )
    db.commit()
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert ticket.column_code == "new" and ticket.manager_id is None
    # The round Zarina solved stays hers and solved; the new one is open.
    solved = [r for r in ticket.reasons if r.get("solved_at")]
    assert solved and solved[0]["solved_by"] == "zarina-asked@shop.test"
    assert [r["code"] for r in ticket.reasons if not r.get("solved_at")] == [
        "meta_error"
    ]
    # Anybody in Support takes it.
    olim = _staff(db, "olim-asked@shop.test", Role.SUPPORT)
    taken = _detail(client.post(f"{URL}/support/take", headers=olim))
    assert taken.id == str(ticket.id) and taken.manager is not None
    assert taken.manager.email == "olim-asked@shop.test"


def test_the_clients_own_refused_press_does_not_reopen_a_closed_ticket(
    client: TestClient, db: Session
) -> None:
    owner, _, ticket = _solved_by(client, db, "press@shop.test", "resolved")
    manager = ticket.manager_id
    db.add(
        ActionLog(
            owner_id=owner.id,
            actor_type="user",
            action="pause",
            target_level="campaign",
            target_external_id="c1",
            target_provider=PROVIDER,
            idempotency_key=uuid.uuid4().hex,
            status="failed",
            error_code="200",
            error_message="Meta refused",
            created_at=utcnow() - timedelta(minutes=40),
        )
    )
    db.commit()

    assert triggers.sweep_support(db, now=utcnow()) == 1
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert ticket.column_code == "resolved" and ticket.manager_id == manager
    assert [r["code"] for r in ticket.reasons] == ["setup"]
    kinds = db.scalars(
        select(BoardCardEvent.kind).where(BoardCardEvent.card_id == ticket.id)
    ).all()
    assert "after_close" in kinds and "reopened" not in kinds
    # Noted once: the next sweep does not meet it again.
    assert triggers.sweep_support(db, now=utcnow()) == 0

    # A press refused for another reason while the ticket is open is a
    # reason on it, as before (the same one again that day is not).
    ticket.column_code = "in_progress"
    db.commit()
    db.add(
        ActionLog(
            owner_id=owner.id,
            actor_type="user",
            action="pause",
            target_level="campaign",
            target_external_id="c1",
            target_provider=PROVIDER,
            idempotency_key=uuid.uuid4().hex,
            status="failed",
            error_code="account_blocked",
            error_message="Meta refused",
            created_at=utcnow() - timedelta(minutes=40),
        )
    )
    db.commit()
    assert triggers.sweep_support(db, now=utcnow()) == 1
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert [r["code"] for r in ticket.reasons] == ["setup", "meta_error"]


def test_a_member_opens_a_closed_ticket_of_another_for_themselves(
    client: TestClient, db: Session
) -> None:
    owner, _, ticket = _solved_by(client, db, "byhand@shop.test", "closed")
    olim = _staff(db, "olim@office.test", Role.SUPPORT)
    opened = client.post(
        f"{URL}/boards/support/cards",
        json={"user_id": str(owner.id), "note": "Yana qo'ng'iroq qildi"},
        headers=olim,
    )
    assert opened.status_code == 201, opened.text
    ticket = _ticket(db, owner)
    assert ticket is not None
    assert ticket.column_code == "in_progress" and ticket.manager_id == olim_id(
        db, "olim@office.test"
    )


def olim_id(db: Session, email: str) -> uuid.UUID:
    from app.modules.accounts.models import User

    found = db.scalar(select(User.id).where(User.email == email))
    assert found is not None
    return found
