"""Calls going on now, against PostgreSQL: the picture kept from UTeL's
events, the socket that tells it, and a client's missed call asking for a
call back on their cards."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.common import tokens
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.schemas import CardDetailOut
from app.modules.telephony import calls
from app.modules.telephony.models import PhoneConnection, PhoneLiveCall
from app.modules.telephony.schemas import LiveOut
from app.modules.telephony.tasks import forget_hook_events_task
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_telephony_calls import _card, _event, _same, _saved, office  # noqa: F401
from tests.pg.test_telephony_settings import exchange  # noqa: F401

URL = "/api/v2/office/telephony"


def _moment(
    name: str,
    call_id: str = "live-1",
    *,
    src: str = "998901234567",
    dst: str = "5200",
    kind: str = "incoming",
    answered_by: str = "",
) -> dict[str, Any]:
    return {
        "time": "14:00:00",
        "data": {
            "name": name,
            "domain": "https://api.utc181.utel.uz",
            "call": {
                "id": call_id,
                "src": src,
                "exten": "6001",
                "cdr": {
                    "src": src,
                    "dst": dst,
                    "external_number": "555550220",
                    "type": kind,
                    "last_answered": answered_by,
                },
            },
        },
    }


def _live(client: TestClient, head: dict[str, str]) -> LiveOut:
    answer = client.get(f"{URL}/live", headers=head)
    assert answer.status_code == 200, answer.text
    return LiveOut.model_validate(answer.json())


def _token(db: Session, email: str) -> str:
    person = db.scalar(select(User).where(User.email == email))
    assert person is not None
    return tokens.issue(subject=str(person.id), kind="access", now=utcnow())


def test_an_incoming_call_rings_is_answered_and_ends(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    owner = _client(db, "shop@shop.test")
    card = _card(db, owner, "sales", "new_lead")
    hook = office["hook"]

    client.post(hook, json=_moment("call_started"))
    (ringing,) = _live(client, office["seller"]).calls
    assert (ringing.state, ringing.direction, ringing.number) == (
        "ringing",
        "in",
        "+998901234567",
    )
    # It has reached a group, which is nobody's number.
    assert ringing.extension == "5200" and ringing.staff is None
    (who,) = ringing.clients
    assert who.email == "shop@shop.test" and who.sales_card_id == str(card.id)
    assert _live(client, office["seller"]).busy == []

    client.post(hook, json=_moment("dial_started", dst="101"))
    (at_seller,) = _live(client, office["boss"]).calls
    assert at_seller.state == "ringing" and at_seller.extension == "101"
    assert at_seller.staff is not None
    assert at_seller.staff.email == "sotuv@office.test"

    client.post(hook, json=_moment("dial_answered", dst="5200", answered_by="102"))
    now = _live(client, office["helper"])
    (talking,) = now.calls
    assert (talking.state, talking.extension) == ("talking", "102")
    assert talking.staff is not None and talking.staff.email == "yordam@office.test"
    assert now.busy == ["102"]

    client.post(hook, json=_moment("dial_ended", dst="102"))
    assert len(_live(client, office["boss"]).calls) == 1
    client.post(hook, json=_moment("call_ended"))
    assert _live(client, office["boss"]).calls == []
    # The saved call arriving after the end changes nothing.
    client.post(hook, json=_event(_saved("live-1")))
    assert db.scalar(select(func.count()).select_from(PhoneLiveCall)) == 0


def test_an_outgoing_call_and_colleagues_calling_each_other(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    hook = office["hook"]
    client.post(
        hook, json=_moment("call_started", "out-1", src="101", dst="935550011", kind="")
    )
    client.post(
        hook, json=_moment("call_started", "inner", src="101", dst="102", kind="")
    )
    client.post(hook, json={"data": {"name": "call_started", "call": "axlat"}})
    client.post(hook, json={"data": {"name": "call_started"}})

    (out,) = _live(client, office["boss"]).calls
    assert (out.direction, out.number, out.extension, out.clients) == (
        "out",
        "+998935550011",
        "101",
        [],
    )
    assert out.staff is not None and out.staff.email == "sotuv@office.test"
    # No end ever came: the saved call closes it too.
    client.post(
        hook, json=_event(_saved("out-1", src="101", dst="935550011", kind="Outgoing"))
    )
    assert _live(client, office["boss"]).calls == []


def test_a_call_whose_end_never_came_leaves_the_picture(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.telephony import tasks

    client.post(office["hook"], json=_moment("call_started", "lost"))
    client.post(office["hook"], json=_moment("call_started", "fresh"))
    row = db.scalar(select(PhoneLiveCall).where(PhoneLiveCall.call_id == "lost"))
    assert row is not None
    row.updated_at = utcnow() - timedelta(hours=4)
    db.commit()

    assert [call.call_id for call in _live(client, office["boss"]).calls] == ["fresh"]
    monkeypatch.setattr(tasks, "task_session", lambda: _same(db))
    forget_hook_events_task.run()
    assert db.scalar(select(func.count()).select_from(PhoneLiveCall)) == 1


def test_the_socket_tells_each_change(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    hook = office["hook"]
    client.post(hook, json=_moment("call_started", "before"))
    _staff(db, "moliya@office.test", Role.FINANCE)
    for bad in ("", "axlat", _token(db, "moliya@office.test")):
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(f"{URL}/ws?token={bad}") as closed,
        ):
            closed.receive_json()

    with client.websocket_connect(
        f"{URL}/ws?token={_token(db, 'sotuv@office.test')}"
    ) as door:
        first = door.receive_json()
        assert first["type"] == "snapshot" and first["busy"] == []
        assert [call["call_id"] for call in first["calls"]] == ["before"]

        client.post(hook, json=_moment("call_started", "now"))
        rang = door.receive_json()
        assert rang["type"] == "call.ringing"
        assert (rang["call"]["call_id"], rang["call"]["number"]) == (
            "now",
            "+998901234567",
        )
        client.post(hook, json=_moment("dial_answered", "now", answered_by="101"))
        took = door.receive_json()
        assert took["type"] == "call.talking"
        assert took["call"]["staff"]["email"] == "sotuv@office.test"
        client.post(hook, json=_moment("call_ended", "now"))
        assert door.receive_json() == {"type": "call.ended", "call_id": "now"}
        # An end of a call we never saw is not told.
        client.post(hook, json=_moment("call_ended", "never"))
        client.post(hook, json=_moment("call_ended", "before"))
        assert door.receive_json() == {"type": "call.ended", "call_id": "before"}
    assert client.get(f"{URL}/live").status_code == 401


def _recent(minutes: int = 1) -> str:
    return (
        (utcnow() - timedelta(minutes=minutes))
        .astimezone(calls.ZONE)
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def test_a_client_s_missed_call_asks_for_a_call_back_on_their_open_cards(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    owner = _client(db, "shop@shop.test")
    sales = _card(db, owner, "sales", "new_lead")
    support = _card(db, owner, "support", "resolved")
    support.closed_at = utcnow()
    later = utcnow() + timedelta(days=2)
    sales.due_at = later
    db.commit()
    missed = _saved("m-1", status="Not answered", talk=0, dst="5200", at=_recent())

    for _ in range(2):  # said twice, written once
        client.post(office["hook"], json=_event(missed))

    db.expire_all()
    kept = db.get(BoardCard, sales.id)
    assert kept is not None and kept.due_at is not None and kept.due_at < later
    assert db.get(BoardCard, support.id).due_at is None  # type: ignore[union-attr]
    lines = list(db.scalars(select(BoardCardEvent)))
    assert [(line.card_id, line.kind, line.ref, line.body) for line in lines] == [
        (sales.id, "missed_call", "call:m-1", "+998901234567")
    ]
    detail = CardDetailOut.model_validate(
        client.get(f"/api/v2/office/cards/{sales.id}", headers=office["boss"]).json()
    )
    assert detail.history[0].label == "Javobsiz qo'ng'iroq"

    # A deadline already passed stays where it was.
    first_due = kept.due_at
    client.post(
        office["hook"],
        json=_event(_saved("m-2", status="Not answered", talk=0, at=_recent(0))),
    )
    db.expire_all()
    assert db.get(BoardCard, sales.id).due_at == first_due  # type: ignore[union-attr]
    assert db.scalar(select(func.count()).select_from(BoardCardEvent)) == 2


def test_other_calls_set_no_deadline(
    client: TestClient,
    db: Session,
    office: dict[str, Any],  # noqa: F811
) -> None:
    owner = _client(db, "shop@shop.test")
    card = _card(db, owner, "sales", "new_lead")
    hook = office["hook"]

    client.post(hook, json=_event(_saved("answered", at=_recent())))
    client.post(
        hook,
        json=_event(
            _saved(
                "ours",
                src="101",
                dst="998901234567",
                kind="Outgoing",
                status="Not answered",
                talk=0,
                at=_recent(),
            )
        ),
    )
    client.post(
        hook,
        json=_event(
            _saved(
                "stranger", src="935550011", status="Not answered", talk=0, at=_recent()
            )
        ),
    )
    # Yesterday's, read from history: on the journal, no call back asked.
    client.post(
        hook,
        json=_event(_saved("old", status="Not answered", talk=0, at=_recent(60 * 13))),
    )

    db.expire_all()
    assert db.get(BoardCard, card.id).due_at is None  # type: ignore[union-attr]
    assert db.scalar(select(func.count()).select_from(BoardCardEvent)) == 0
    assert db.scalar(select(func.count()).select_from(PhoneConnection)) == 1
