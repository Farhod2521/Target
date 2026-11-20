"""What waits on a pair's board, and the owner's daily message saying so."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.chat.selectors.daily import weekly_book
from app.modules.crm.models import CrmCard
from app.modules.crm.selectors.backlog import Backlog, backlog_by_pair
from app.modules.notifications.services.compose_day_pair import (
    crm_lines,
    pair_message,
)
from tests.pg.test_crm_http import CRM, LATER, _auth, _owner, _running

PAIR = ("page_1", "act_1")


def _stage(board: dict, kind: str) -> str:  # type: ignore[type-arg]
    return next(
        c["stage"]["id"] for c in board["columns"] if c["stage"]["kind"] == kind
    )


def test_a_board_that_is_not_on_has_nothing_waiting(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)

    assert backlog_by_pair(db, owner=owner, now=utcnow()) == {}


def test_new_leads_wait_only_after_an_hour(client: TestClient, db: Session) -> None:
    owner = _owner(db)
    _running(client, _auth(owner))
    now = utcnow()

    fresh = backlog_by_pair(db, owner=owner, now=now)
    later = backlog_by_pair(db, owner=owner, now=now + timedelta(hours=2))

    assert fresh == {PAIR: Backlog()}
    assert not fresh[PAIR]
    assert later == {PAIR: Backlog(untaken=3)}


def test_late_cards_and_qualified_leads_left_a_week_are_counted(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    due, quiet, sold = (c["id"] for c in board["columns"][0]["cards"])
    working = _stage(board, "open")
    quality = client.post(
        f"{CRM}/settings/quality", headers=head, json={"quality": [working]}
    )
    assert quality.is_success, quality.text
    for card in (due, quiet):
        assert client.post(
            f"{CRM}/cards/{card}/move", headers=head, json={"to": working}
        ).is_success
    assert client.post(
        f"{CRM}/cards/{due}/due", headers=head, json={"due": LATER}
    ).is_success
    assert client.post(
        f"{CRM}/cards/{sold}/win", headers=head, json={"amount": "10"}
    ).is_success
    now = utcnow()
    # One card's due time has passed; the other was last touched nine days ago.
    db.execute(
        update(CrmCard).where(CrmCard.id == due).values(due_at=now - timedelta(hours=1))
    )
    db.execute(
        update(CrmCard)
        .where(CrmCard.id == quiet)
        .values(updated_at=now - timedelta(days=9))
    )
    db.commit()

    found = backlog_by_pair(db, owner=owner, now=now)

    # The sold card waits for nobody, late or stale.
    assert found == {PAIR: Backlog(untaken=0, late=1, stale=1)}
    assert db.scalar(select(CrmCard.qualified_at).where(CrmCard.id == quiet))


def test_the_owners_message_names_what_waits_on_the_board(
    client: TestClient, db: Session
) -> None:
    owner = _owner(db)
    _running(client, _auth(owner))
    db.execute(update(CrmCard).values(created_at=utcnow() - timedelta(hours=3)))
    db.commit()

    book = weekly_book(db, owner=db.get(User, owner.id), now=utcnow())

    (report,) = book.reports
    assert (report.crm_untaken, report.crm_late, report.crm_stale) == (3, 0, 0)
    assert crm_lines(report) == ["CRM: 3 ta yangi lid hali olinmagan"]
    assert (
        "CRM: 3 ta yangi lid hali olinmagan"
        in pair_message(book=book, report=report).text
    )


def test_a_quiet_board_adds_no_line(client: TestClient, db: Session) -> None:
    owner = _owner(db)

    book = weekly_book(db, owner=db.get(User, owner.id), now=utcnow())

    assert all(crm_lines(report) == [] for report in book.reports)
