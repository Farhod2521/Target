"""Telephony's calls against PostgreSQL: a finished call UTeL sends is kept
once, shown on the client's cards and on the journal; strangers' calls stay
on the journal alone; the hourly read brings what a hook did not."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.boards.models import BoardCard
from app.modules.boards.schemas import CardDetailOut
from app.modules.telephony import calls, utel
from app.modules.telephony.models import PhoneCall, PhoneConnection, PhoneHookEvent
from app.modules.telephony.schemas import JournalOut
from app.modules.telephony.tasks import backfill_calls_task, forget_hook_events_task
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_telephony_settings import LOGIN, Exchange, exchange  # noqa: F401

URL = "/api/v2/office/telephony"
AUDIO = "https://api.utc181.utel.uz/storage/monitor/2026/11/12/1.wav"


def _saved(
    call_id: str,
    *,
    src: str = "998901234567",
    dst: str = "101",
    kind: str = "Incoming",
    status: str = "Answered",
    talk: int = 60,
    at: str = "2026-11-12 14:00:00",
    audio: str = AUDIO,
) -> dict[str, Any]:
    return {
        "id": 1,
        "call_id": call_id,
        "date_time": at,
        "src": src,
        "dst": dst,
        "external_number": "555550220",
        "duration": talk + 5,
        "conversation": talk,
        "type": {"number": 0, "name": kind},
        "status": {"number": 0, "name": status},
        "recorded_file_url": audio,
        "integration": [],
    }


def _event(item: dict[str, Any]) -> dict[str, Any]:
    return {"time": "14:01:05", "data": {"name": "call_saved", "call_history": item}}


@pytest.fixture
def office(
    client: TestClient,
    db: Session,
    exchange: Exchange,  # noqa: F811
) -> dict[str, Any]:
    """A connected office: 101 is the seller's, 102 the support person's."""
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "sotuv@office.test", Role.SALES)
    helper = _staff(db, "yordam@office.test", Role.SUPPORT)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)
    state = client.put(f"{URL}/connection", json=LOGIN, headers=boss).json()
    people = {
        person.email: person for person in db.scalars(select(User).where(User.is_staff))
    }
    for seat, email in zip(
        state["extensions"], ("sotuv@office.test", "yordam@office.test"), strict=True
    ):
        client.patch(
            f"{URL}/extensions/{seat['id']}",
            json={"user_id": str(people[email].id)},
            headers=boss,
        )
    key = db.scalar(select(PhoneConnection.hook_key))
    return {
        "boss": boss,
        "seller": seller,
        "helper": helper,
        "lead": lead,
        "people": people,
        "hook": f"/webhooks/utel/{key}",
        "exchange": exchange,
    }


def _card(db: Session, owner: User, board: str, column: str) -> BoardCard:
    now = utcnow()
    card = BoardCard(
        board=board,
        owner_id=owner.id,
        column_code=column,
        opened_at=now,
        column_since=now,
    )
    db.add(card)
    db.commit()
    return card


def _journal(client: TestClient, head: dict[str, str], **params: Any) -> JournalOut:
    answer = client.get(f"{URL}/calls", params=params, headers=head)
    assert answer.status_code == 200, answer.text
    return JournalOut.model_validate(answer.json())


def test_connecting_asks_for_the_last_month_of_calls(
    office: dict[str, Any], queued: list[tuple[str, tuple[object, ...]]]
) -> None:
    assert ("app.modules.telephony.tasks.backfill_calls_task", (720,)) in queued


def test_a_saved_call_is_on_both_of_the_client_s_cards(
    client: TestClient, db: Session, office: dict[str, Any]
) -> None:
    owner = _client(db, "shop@shop.test")
    sales = _card(db, owner, "sales", "new_lead")
    support = _card(db, owner, "support", "new")

    for _ in range(2):  # UTeL saying it twice keeps one call
        sent = client.post(office["hook"], json=_event(_saved("c-1")))
        assert sent.json() == {"ok": True}
    client.post(
        office["hook"],
        json=_event(
            _saved(
                "c-2",
                src="102",
                dst="+998 90 123-45-67",
                kind="Outgoing",
                status="Not answered",
                talk=0,
                at="2026-11-12 15:00:00",
                audio="",
            )
        ),
    )

    assert db.scalar(select(func.count()).select_from(PhoneCall)) == 2
    for card in (sales, support):
        detail = CardDetailOut.model_validate(
            client.get(f"/api/v2/office/cards/{card.id}", headers=office["boss"]).json()
        )
        out, came = detail.calls
        assert (came.direction, came.answered, came.number) == (
            "in",
            True,
            "+998901234567",
        )
        assert came.direction_label == "Kiruvchi"
        assert (came.talk_seconds, came.duration_seconds) == (60, 65)
        assert came.extension == "101" and came.has_recording
        assert came.staff is not None and came.staff.email == "sotuv@office.test"
        # 14:00 on the exchange's clock, Tashkent.
        assert came.started_at == datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
        assert (out.direction, out.answered, out.has_recording) == ("out", False, False)
        assert out.staff is not None and out.staff.email == "yordam@office.test"
    assert (
        AUDIO
        not in client.get(
            f"/api/v2/office/cards/{sales.id}", headers=office["boss"]
        ).text
    )


def test_a_stranger_s_call_stays_on_the_journal_and_opens_no_card(
    client: TestClient, db: Session, office: dict[str, Any]
) -> None:
    owner = _client(db, "shop@shop.test")
    card = _card(db, owner, "sales", "new_lead")
    client.post(office["hook"], json=_event(_saved("known")))
    client.post(
        office["hook"],
        json=_event(
            _saved(
                "stranger", src="935550011", status="Not answered", talk=0, dst="5200"
            )
        ),
    )
    # Colleagues calling each other, and a row with no id, are not kept.
    client.post(
        office["hook"], json=_event(_saved("inner", src="101", dst="102", kind=""))
    )
    client.post(office["hook"], json=_event(_saved("")))

    assert db.scalar(select(func.count()).select_from(BoardCard)) == 1
    everything = _journal(client, office["boss"])
    assert everything.total == 2
    unknown = _journal(client, office["boss"], scope="unknown")
    (lost,) = unknown.calls
    assert (lost.number, lost.answered, lost.clients) == ("+998935550011", False, [])
    # It rang on a group, which is nobody's number.
    assert lost.extension == "5200" and lost.staff is None
    known = _journal(client, office["boss"], scope="known")
    (mine,) = known.calls
    (who,) = mine.clients
    assert who.email == "shop@shop.test"
    assert who.sales_card_id == str(card.id) and who.support_card_id is None

    assert _journal(client, office["boss"], answered=False).total == 1
    assert _journal(client, office["boss"], direction="out").total == 0
    assert _journal(client, office["boss"], q="555-00").total == 1
    assert _journal(client, office["boss"], q="000000").total == 0
    paged = _journal(client, office["boss"], limit=1, offset=1)
    assert paged.total == 2 and len(paged.calls) == 1

    # Signing up afterwards, the stranger is a client and the call is theirs.
    late = _client(db, "yangi@shop.test")
    late.phone = "+998935550011"
    db.commit()
    assert _journal(client, office["boss"], scope="unknown").total == 0


def test_who_sees_which_calls(
    client: TestClient, db: Session, office: dict[str, Any]
) -> None:
    client.post(office["hook"], json=_event(_saved("sellers")))
    client.post(office["hook"], json=_event(_saved("helpers", dst="102")))
    client.post(
        office["hook"],
        json=_event(_saved("missed", dst="5200", status="Not answered", talk=0)),
    )
    outsider = _staff(db, "moliya@office.test", Role.FINANCE)

    assert _journal(client, office["boss"]).total == 3
    assert _journal(client, office["lead"]).total == 3
    seen = _journal(client, office["seller"])
    assert {(c.extension, c.answered) for c in seen.calls} == {
        ("101", True),
        ("5200", False),
    }
    assert _journal(client, office["seller"], mine=True).total == 1
    assert client.get(f"{URL}/calls", headers=outsider).status_code == 404
    assert client.get(f"{URL}/calls").status_code == 401

    theirs = db.scalar(select(PhoneCall.id).where(PhoneCall.call_id == "helpers"))
    refused = client.get(f"{URL}/calls/{theirs}/recording", headers=office["seller"])
    assert refused.status_code == 404 and refused.json()["code"] == "call_not_found"


def test_the_recording_is_passed_on_from_utel_alone(
    client: TestClient,
    db: Session,
    office: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    def send(self: httpx.Client, request: httpx.Request, **_: Any) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(
            200, content=b"RIFFovoz", headers={"content-type": "audio/x-wav"}
        )

    monkeypatch.setattr(httpx.Client, "send", send)
    client.post(office["hook"], json=_event(_saved("good")))
    client.post(office["hook"], json=_event(_saved("silent", audio="")))
    # A link that is not the exchange's own is not kept at all.
    client.post(
        office["hook"],
        json=_event(_saved("forged", audio="https://evil.example/storage/1.wav")),
    )
    client.post(
        office["hook"],
        json=_event(_saved("inner", audio="http://api.utc181.utel.uz/x.wav")),
    )
    ids = dict(db.execute(select(PhoneCall.call_id, PhoneCall.id)).all())

    played = client.get(
        f"{URL}/calls/{ids['good']}/recording", headers=office["seller"]
    )
    assert played.status_code == 200 and played.content == b"RIFFovoz"
    assert played.headers["content-type"] == "audio/x-wav"
    assert asked == [AUDIO]
    for name in ("silent", "forged", "inner"):
        none = client.get(f"{URL}/calls/{ids[name]}/recording", headers=office["boss"])
        assert none.status_code == 404 and none.json()["code"] == "no_recording", name
    assert asked == [AUDIO]
    assert client.get(f"{URL}/calls/{ids['good']}/recording").status_code == 401


def test_the_hourly_read_brings_what_no_hook_brought(
    client: TestClient,
    db: Session,
    office: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.telephony import tasks

    client.post(
        office["hook"], json=_event(_saved("both", status="Not answered", talk=0))
    )
    pages = {
        1: [_saved("both", talk=90), _saved("late-1", src="935550011")],
        2: [_saved("late-2", src="101", dst="998935550011", kind="Outgoing")],
    }
    asked: list[dict[str, Any]] = []

    def history(tenant: str, **options: Any) -> tuple[list[dict[str, Any]], int]:
        asked.append({"tenant": tenant} | options)
        return pages[options["page"]], 2

    monkeypatch.setattr(utel, "call_history", history)
    monkeypatch.setattr(tasks, "task_session", lambda: _same(db))

    assert backfill_calls_task.run() == 3

    assert [call["page"] for call in asked] == [1, 2]
    assert asked[0]["tenant"] == "utc181" and asked[0]["token"] == "1|kalit"
    span = asked[0]["end"] - asked[0]["start"]
    assert timedelta(hours=3) <= span <= timedelta(hours=3, minutes=2)
    assert str(asked[0]["start"].tzinfo) == "Asia/Tashkent"
    rows = {
        row.call_id: row
        for row in db.scalars(
            select(PhoneCall).execution_options(populate_existing=True)
        )
    }
    assert set(rows) == {"both", "late-1", "late-2"}
    # The later word replaces the earlier; who took it stays.
    assert rows["both"].answered and rows["both"].talk_seconds == 90
    assert rows["both"].user_id == office["people"]["sotuv@office.test"].id
    assert (
        rows["late-2"].direction == "out" and rows["late-2"].number == "+998935550011"
    )

    # UTeL down or the key refused: the task ends quietly.
    def down(tenant: str, **options: Any) -> tuple[list[dict[str, Any]], int]:
        raise utel.Unreachable

    monkeypatch.setattr(utel, "call_history", down)
    assert backfill_calls_task.run() == 0


class _same:
    """The test's own session where a task would open one."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def __enter__(self) -> Session:
        return self.db

    def __exit__(self, *_: object) -> None:
        return None


def test_old_raw_events_go_and_the_calls_stay(
    client: TestClient,
    db: Session,
    office: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.telephony import tasks

    client.post(office["hook"], json=_event(_saved("old")))
    client.post(office["hook"], json=_event(_saved("new")))
    first = db.scalar(select(PhoneHookEvent).order_by(PhoneHookEvent.received_at))
    assert first is not None
    first.received_at = utcnow() - timedelta(days=15)
    db.commit()
    monkeypatch.setattr(tasks, "task_session", lambda: _same(db))

    assert forget_hook_events_task.run() == 1

    assert db.scalar(select(func.count()).select_from(PhoneHookEvent)) == 1
    assert db.scalar(select(func.count()).select_from(PhoneCall)) == 2


def test_numbers_are_written_the_way_a_client_s_phone_is_kept() -> None:
    assert calls.as_phone("998901234567") == "+998901234567"
    assert calls.as_phone("901234567") == "+998901234567"
    assert calls.as_phone("+998 (90) 123-45-67") == "+998901234567"
    # Nine digits beginning with 998 are a local number too.
    assert calls.as_phone("998123456") == "+998998123456"
    assert calls.as_phone("77005551235") == "+77005551235"
    assert calls.as_phone("101") == "101" and calls.as_phone("") == ""
    assert calls.is_extension("5200") and not calls.is_extension("901234567")


def test_a_flat_event_and_bare_codes_are_read_too(
    client: TestClient, db: Session, office: dict[str, Any]
) -> None:
    item = _saved("flat") | {"type": 2, "status": 1, "src": "101", "dst": "935550011"}
    sent = client.post(
        office["hook"], json={"name": "call_saved", "call_history": item}
    )
    assert sent.json() == {"ok": True}
    # No type at all: an internal number calling out is outgoing.
    bare = _saved("bare", src="102", dst="935550011") | {"type": None, "status": None}
    client.post(office["hook"], json=_event(bare))
    # A call that cannot be read keeps its event and breaks nothing.
    client.post(office["hook"], json=_event({"call_id": "odd", "src": [], "dst": {}}))

    rows = {row.call_id: row for row in db.scalars(select(PhoneCall))}
    assert set(rows) == {"flat", "bare"}
    assert (rows["flat"].direction, rows["flat"].answered) == ("out", True)
    assert (rows["bare"].direction, rows["bare"].answered) == ("out", True)
    assert db.scalar(select(func.count()).select_from(PhoneHookEvent)) == 3
