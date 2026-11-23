"""The assistant knows the client's request to Support: where it stands,
what it is about, whether Support wrote in the chat - and it does not
prepare a second request for a problem Support already has in hand."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.assistant.selectors.health import account_health
from app.modules.assistant.selectors.support_request import support_request
from app.modules.boards.constants import EventKind, TicketReason
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.tickets import raise_ticket
from app.modules.chat.selectors.scope import current_page_scope
from core.assistant.tools import TicketDraft
from core.chat.lookup_arguments import Nothing
from tests.pg.test_assistant import _ask, _Script, _with_plan

DRAFT = TicketDraft(summary="Kartadan pul yechilmayapti, tekshirib bering.")


def _request(db: Session, owner, words: str = "Kartadan pul yechilmayapti") -> BoardCard:
    raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.AI,
        ref=f"ai-chat:{words}",
        now=utcnow() - timedelta(hours=2),
        detail=words,
    )
    db.commit()
    card = db.scalar(select(BoardCard).where(BoardCard.owner_id == owner.id))
    assert card is not None
    return card


def _health(db: Session, owner) -> str:
    return account_health(
        db, owner=owner, scope=current_page_scope(db, owner=owner), now=utcnow()
    )


def test_no_request_is_said_so(client: TestClient, db: Session) -> None:
    _headers, owner = _with_plan(client, db)
    text = _health(db, owner)
    assert "## Request to Support" in text
    assert "no request to Support is open" in text


def test_an_open_request_is_shown_with_its_topic_and_no_chat_reply(
    client: TestClient, db: Session
) -> None:
    _headers, owner = _with_plan(client, db)
    _request(db, owner)
    text = _health(db, owner)
    assert "in Support's queue" in text
    assert "about: Kartadan pul yechilmayapti" in text
    assert "Never say a reply is waiting in the chat" in text
    assert "prepare no new request" in text


def test_a_second_request_for_the_same_problem_is_refused(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner = _with_plan(client, db)
    _request(db, owner)
    script = _Script(calls=[("account_health", Nothing()), ("create_ticket", DRAFT)])
    turn = _ask(client, db, headers, monkeypatch, script, question="Pul yechilmayapti")
    assert script.seen[1].startswith("Not prepared: Support already has")
    assert "Kartadan pul yechilmayapti" in script.seen[1]
    answer = client.get(
        f"/api/v2/assistant/threads/{turn['session_id']}", headers=headers
    ).json()["messages"][1]
    assert answer["buttons"] == []


def test_a_different_problem_is_prepared_all_the_same(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner = _with_plan(client, db)
    _request(db, owner)
    other = TicketDraft(
        summary="Darslik videosi ochilmayapti, tekshirib bering.", new_problem=True
    )
    script = _Script(calls=[("create_ticket", other)])
    _ask(client, db, headers, monkeypatch, script, question="Darslik ochilmayapti")
    assert "nothing has been sent" in script.seen[0]


def test_a_solved_request_carries_what_was_done_and_a_new_one_may_be_prepared(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner = _with_plan(client, db)
    card = _request(db, owner)
    card.column_code = "confirming"
    card.column_since = utcnow()
    db.add(
        BoardCardEvent(
            card_id=card.id,
            owner_id=owner.id,
            kind=str(EventKind.RESOLVED),
            from_column="in_progress",
            to_column="confirming",
            body="gaplashdim, kartani qayta uladik",
        )
    )
    db.commit()

    found = support_request(db, owner=owner, now=utcnow())
    assert found is not None and not found.in_hand
    text = _health(db, owner)
    assert "marked it solved" in text
    assert "gaplashdim, kartani qayta uladik" in text
    assert "prepare no new request" not in text

    script = _Script(calls=[("create_ticket", DRAFT)])
    _ask(client, db, headers, monkeypatch, script, question="Hali ham ishlamayapti")
    assert "nothing has been sent" in script.seen[0]


def test_a_request_solved_long_ago_is_not_shown(client: TestClient, db: Session) -> None:
    _headers, owner = _with_plan(client, db)
    card = _request(db, owner)
    card.column_code = "resolved"
    card.column_since = utcnow() - timedelta(days=5)
    db.commit()
    assert support_request(db, owner=owner, now=utcnow()) is None


def test_a_request_in_a_column_of_the_offices_own_is_named_by_it(
    client: TestClient, db: Session
) -> None:
    """The superuser adds columns to the Support board: the assistant names
    such a step by its name, never by its code, and Support still has it."""
    from app.modules.boards.models import BoardColumn

    _headers, owner = _with_plan(client, db)
    card = _request(db, owner)
    db.add(
        BoardColumn(
            board="support",
            code="c_bank000001",
            name="Bank javobi kutilmoqda",
            position=99,
            kind="manual",
            is_custom=True,
        )
    )
    card.column_code = "c_bank000001"
    db.commit()
    found = support_request(db, owner=owner, now=utcnow())
    assert found is not None and found.in_hand
    assert found.column_name == "Bank javobi kutilmoqda"
    text = _health(db, owner)
    assert "it stands at the step «Bank javobi kutilmoqda»" in text
    assert "c_bank000001" not in text
    assert "prepare no new request" in text
