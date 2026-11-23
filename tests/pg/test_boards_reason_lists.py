"""The boards' lists of reasons against PostgreSQL: what they start with,
the superuser's changes, and each list asked where it belongs (closing a
lead, declining a renewal, a call that did not reach, a move by hand)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.boards import triggers
from app.modules.boards.models import BoardCard
from app.modules.boards.schemas import (
    CardDetailOut,
    ReasonListsOut,
    ReasonOut,
    ReasonRowOut,
    SalesReportOut,
)
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import _live

URL = "/api/v2/office"


def _reasons(client: TestClient, head: dict[str, str], board: str, purpose: str = ""):
    answer = client.get(
        f"{URL}/boards/{board}/reasons", params={"purpose": purpose}, headers=head
    )
    assert answer.status_code == 200, answer.text
    return [ReasonOut.model_validate(item) for item in answer.json()]


def _add(
    client: TestClient,
    head: dict[str, str],
    board: str,
    purpose: str,
    name: str,
    **more,
) -> ReasonRowOut:
    answer = client.post(
        f"{URL}/boards/{board}/reason-lists/{purpose}",
        json={"name": name, **more},
        headers=head,
    )
    assert answer.status_code == 201, answer.text
    return ReasonRowOut.model_validate(answer.json())


def _lead(client: TestClient, db: Session, head: dict[str, str]) -> CardDetailOut:
    _live(db)
    _client(db, f"lead{utcnow().timestamp()}@shop.test")
    triggers.sweep_sales(db, now=utcnow())
    taken = client.post(f"{URL}/sales/take", headers=head)
    assert taken.status_code == 200, taken.text
    return CardDetailOut.model_validate(taken.json())


def test_the_lists_start_with_what_the_code_had(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    close = _reasons(client, boss, "sales")
    assert [(r.value, r.label, r.note_required) for r in close] == [
        ("expensive", "Qimmat", False),
        ("not_needed", "Kerak emas", False),
        ("no_answer", "Javob bermaydi", False),
        ("wrong_number", "Raqam noto'g'ri", False),
        ("other", "Boshqa", True),
    ]
    decline = _reasons(client, boss, "renewal")
    assert [r.value for r in decline] == [
        "expensive",
        "no_result",
        "meta_problem",
        "business_stopped",
        "switched",
        "no_answer",
        "other",
    ]
    assert decline[-1].note_required
    # Nothing new is asked until the superuser writes a reason.
    assert _reasons(client, boss, "sales", "no_contact") == []
    assert _reasons(client, boss, "sales", "move") == []
    assert _reasons(client, boss, "support") == []
    assert (
        client.get(
            f"{URL}/boards/support/reasons", params={"purpose": "close"}, headers=boss
        ).status_code
        == 404
    )

    lists = ReasonListsOut.model_validate(
        client.get(f"{URL}/boards/sales/reason-lists", headers=boss).json()
    )
    assert lists.may_edit
    assert [item.purpose for item in lists.lists] == ["close", "no_contact", "move"]
    assert all(row.is_default for row in lists.lists[0].rows)
    support = ReasonListsOut.model_validate(
        client.get(f"{URL}/boards/support/reason-lists", headers=boss).json()
    )
    assert [item.purpose for item in support.lists] == ["move"]


def test_only_the_superuser_changes_a_list(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    owner = _staff(db, "egasi@office.test", Role.OWNER)
    seller = _staff(db, "ali@office.test", Role.SALES)
    support = _staff(db, "zarina@office.test", Role.SUPPORT)
    path = f"{URL}/boards/sales/reason-lists"

    added = _add(client, boss, "sales", "close", "  Raqobatchini   tanladi ")
    assert added.name == "Raqobatchini tanladi" and added.code.startswith("r_")
    assert added.position == 6 and not added.is_default and not added.note_required
    again = client.post(
        f"{path}/close", json={"name": "raqobatchini tanladi"}, headers=boss
    )
    assert again.status_code == 422 and again.json()["code"] == "reason_name_taken"
    assert (
        client.post(f"{path}/close", json={"name": "  "}, headers=boss).status_code
        == 422
    )
    assert (
        client.post(f"{path}/decline", json={"name": "X"}, headers=boss).status_code
        == 404
    )

    row = f"{path}/close/{added.id}"
    body = {"name": "Y", "position": 1, "note_required": False}
    for head, refused in ((owner, 403), (seller, 404), (support, 404)):
        assert (
            client.post(f"{path}/close", json={"name": "Y"}, headers=head).status_code
            == refused
        )
        assert client.put(row, json=body, headers=head).status_code == refused
        assert client.post(f"{row}/archive", headers=head).status_code == refused
        assert client.post(f"{row}/restore", headers=head).status_code == refused
    # The Owner and the board's people read the lists; only the superuser edits.
    read = ReasonListsOut.model_validate(client.get(path, headers=owner).json())
    assert not read.may_edit and len(read.lists[0].rows) == 6
    assert client.get(path, headers=support).status_code == 404

    edited = ReasonRowOut.model_validate(
        client.put(
            row,
            json={"name": "Raqobatchiga ketdi", "position": 0, "note_required": True},
            headers=boss,
        ).json()
    )
    assert edited.name == "Raqobatchiga ketdi" and edited.code == added.code
    first = _reasons(client, seller, "sales")[0]
    assert (first.value, first.note_required) == (added.code, True)
    # The wrong list's id is no reason of this one.
    assert (
        client.post(f"{path}/move/{added.id}/archive", headers=boss).status_code == 404
    )

    archived = ReasonRowOut.model_validate(
        client.post(f"{row}/archive", headers=boss).json()
    )
    assert archived.is_archived
    assert added.code not in [r.value for r in _reasons(client, seller, "sales")]
    kept = ReasonListsOut.model_validate(client.get(path, headers=boss).json())
    assert added.code in [r.code for r in kept.lists[0].rows]
    restored = client.post(f"{row}/restore", headers=boss).json()
    assert restored["is_archived"] is False


def test_a_lead_closes_with_a_reason_of_the_list(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    own = _add(client, boss, "sales", "close", "Raqobatchini tanladi")
    card = _lead(client, db, seller)
    press = f"{URL}/cards/{card.id}/actions"
    assert next(a for a in card.actions if a.value == "close").reason == "close"
    assert next(a for a in card.actions if a.value == "no_contact").reason == ""

    none = client.post(press, json={"action": "close"}, headers=seller)
    assert none.status_code == 422 and none.json()["code"] == "reason_required"
    unknown = client.post(
        press, json={"action": "close", "reason": "nothing"}, headers=seller
    )
    assert unknown.status_code == 422
    bare = client.post(
        press, json={"action": "close", "reason": "other"}, headers=seller
    )
    assert bare.status_code == 422 and bare.json()["code"] == "note_required"

    closed = CardDetailOut.model_validate(
        client.post(
            press, json={"action": "close", "reason": own.code}, headers=seller
        ).json()
    )
    assert closed.close_reason == own.code
    assert closed.close_reason_label == "Raqobatchini tanladi"

    # Renamed, then archived: the closed card and the report read the new words.
    row = f"{URL}/boards/sales/reason-lists/close/{own.id}"
    client.put(row, json={"name": "Raqobatchi", "position": 6}, headers=boss)
    client.post(f"{row}/archive", headers=boss)
    seen = CardDetailOut.model_validate(
        client.get(f"{URL}/cards/{card.id}", headers=boss).json()
    )
    assert seen.close_reason_label == "Raqobatchi"
    today = utcnow().date()
    report = SalesReportOut.model_validate(
        client.get(
            f"{URL}/boards/sales/report",
            params={
                "date_from": str(today - timedelta(days=1)),
                "date_to": str(today + timedelta(days=1)),
            },
            headers=boss,
        ).json()
    )
    assert [(r.code, r.label, r.count) for r in report.reasons] == [
        (own.code, "Raqobatchi", 1)
    ]
    # Archived: not to be picked any more.
    other = _lead(client, db, seller)
    refused = client.post(
        f"{URL}/cards/{other.id}/actions",
        json={"action": "close", "reason": own.code},
        headers=seller,
    )
    assert refused.status_code == 422


def test_no_contact_asks_for_a_reason_once_the_list_has_one(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    card = _lead(client, db, seller)
    press = f"{URL}/cards/{card.id}/actions"

    # An empty list: the button works as it always did.
    plain = CardDetailOut.model_validate(
        client.post(press, json={"action": "no_contact"}, headers=seller).json()
    )
    assert plain.column == "no_contact" and plain.attempts == 1

    off = _add(client, boss, "sales", "no_contact", "Telefon o'chiq")
    busy = _add(client, boss, "sales", "no_contact", "Boshqa", note_required=True)
    asked = CardDetailOut.model_validate(
        client.get(f"{URL}/cards/{card.id}", headers=seller).json()
    )
    assert (
        next(a for a in asked.actions if a.value == "no_contact").reason == "no_contact"
    )

    none = client.post(press, json={"action": "no_contact"}, headers=seller)
    assert none.status_code == 422 and none.json()["code"] == "reason_required"
    bare = client.post(
        press, json={"action": "no_contact", "reason": busy.code}, headers=seller
    )
    assert bare.status_code == 422 and bare.json()["code"] == "note_required"
    # A refused press counts no attempt.
    db.expire_all()
    assert db.scalar(select(BoardCard.attempts).where(BoardCard.id == card.id)) == 1

    said = CardDetailOut.model_validate(
        client.post(
            press,
            json={"action": "no_contact", "reason": off.code, "note": "Ikki marta"},
            headers=seller,
        ).json()
    )
    assert said.attempts == 2
    assert said.history[0].kind == "no_contact"
    assert said.history[0].body.startswith("Telefon o'chiq. Ikki marta")

    # The other boards' lists are their own.
    assert _reasons(client, boss, "renewal", "no_contact") == []


def test_a_move_by_hand_takes_a_reason_from_its_list(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    seller = _staff(db, "ali@office.test", Role.SALES)
    card = _lead(client, db, seller)
    move = f"{URL}/cards/{card.id}/move"

    # An empty list: the mover's own words, required as before.
    blank = client.post(move, json={"column": "contacted"}, headers=boss)
    assert blank.status_code == 422 and blank.json()["code"] == "move_reason_required"
    free = CardDetailOut.model_validate(
        client.post(
            move, json={"column": "contacted", "reason": "Xato ustunda"}, headers=boss
        ).json()
    )
    assert free.history[0].body == "Xato ustunda"

    dup = _add(client, boss, "sales", "move", "Dublikat")
    words = _add(client, boss, "sales", "move", "Boshqa", note_required=True)
    unlisted = client.post(
        move, json={"column": "callback", "reason": "o'zim yozdim"}, headers=boss
    )
    assert unlisted.status_code == 422 and unlisted.json()["code"] == "reason_required"
    bare = client.post(
        move, json={"column": "callback", "reason_code": words.code}, headers=boss
    )
    assert bare.status_code == 422 and bare.json()["code"] == "note_required"
    listed = CardDetailOut.model_validate(
        client.post(
            move, json={"column": "callback", "reason_code": dup.code}, headers=boss
        ).json()
    )
    assert listed.column == "callback" and listed.history[0].body == "Dublikat"
    both = CardDetailOut.model_validate(
        client.post(
            move,
            json={"column": "contacted", "reason_code": words.code, "reason": "Sinov"},
            headers=boss,
        ).json()
    )
    assert both.history[0].body == "Boshqa. Sinov"
