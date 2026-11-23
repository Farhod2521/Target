"""The superuser's own columns against PostgreSQL: adding one, its place,
who may, taking it off and putting it back, and a card moved through it."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.backoffice.constants import Role
from app.modules.boards import triggers
from app.modules.boards.models import BoardCard, BoardColumn
from app.modules.boards.schemas import BoardViewOut, CardDetailOut, ColumnsOut, MeOut
from tests.pg.test_boards_me import _staff
from tests.pg.test_boards_sales import _client
from tests.pg.test_boards_support import _live

URL = "/api/v2/office"


def _out(answer: object) -> ColumnsOut:
    assert answer.status_code in (200, 201), answer.text  # type: ignore[attr-defined]
    return ColumnsOut.model_validate(answer.json())  # type: ignore[attr-defined]


def _names(body: ColumnsOut) -> list[str]:
    return [column.name for column in body.columns]


def test_the_superuser_adds_a_column_where_they_say(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    path = f"{URL}/boards/sales/columns"
    before = _out(client.get(path, headers=boss))
    assert before.may_edit and not before.removed
    assert not any(column.is_custom for column in before.columns)

    added = _out(
        client.post(path, json={"name": "  Demo   ko'rsatildi "}, headers=boss)
    )
    names = _names(added)
    # With no place named: before the first final column (Sotildi).
    assert names.index("Demo ko'rsatildi") == names.index("Sotildi") - 1
    new = next(column for column in added.columns if column.is_custom)
    assert new.code.startswith("c_") and len(new.code) <= 24
    assert new.kind == "manual" and not new.is_final and not new.is_default_name
    assert [column.position for column in added.columns] == sorted(
        column.position for column in added.columns
    )

    placed = _out(
        client.post(
            path, json={"name": "Hujjat kutilmoqda", "after": "new_lead"}, headers=boss
        )
    )
    names = _names(placed)
    assert names.index("Hujjat kutilmoqda") == names.index("Yangi lead") + 1
    # The hidden columns still stand after every visible one.
    hidden = list(
        db.scalars(
            select(BoardColumn.position).where(
                BoardColumn.board == "sales", BoardColumn.is_visible.is_(False)
            )
        )
    )
    assert min(hidden) > len(placed.columns)
    # The other boards are untouched.
    support = _out(client.get(f"{URL}/boards/support/columns", headers=boss))
    assert not any(column.is_custom for column in support.columns)


def test_a_new_column_is_refused_when_it_cannot_be(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    path = f"{URL}/boards/support/columns"

    blank = client.post(path, json={"name": "   "}, headers=boss)
    assert blank.status_code == 422
    taken = client.post(path, json={"name": "yangi"}, headers=boss)
    assert taken.status_code == 422 and taken.json()["code"] == "column_name_taken"
    nowhere = client.post(path, json={"name": "X", "after": "sold"}, headers=boss)
    assert nowhere.status_code == 422 and nowhere.json()["code"] == "no_such_column"

    have = len(_out(client.get(path, headers=boss)).columns)
    for index in range(20 - have):
        _out(client.post(path, json={"name": f"Ustun {index}"}, headers=boss))
    full = client.post(path, json={"name": "Ortiqcha"}, headers=boss)
    assert full.status_code == 422 and full.json()["code"] == "too_many_columns"


def test_only_the_superuser_changes_columns(client: TestClient, db: Session) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    owner = _staff(db, "egasi@office.test", Role.OWNER)
    lead = _staff(db, "rahbar@office.test", Role.SALES_LEAD)
    support = _staff(db, "support@office.test", Role.SUPPORT)
    path = f"{URL}/boards/sales/columns"
    code = next(
        column.code
        for column in _out(
            client.post(path, json={"name": "Demo"}, headers=boss)
        ).columns
        if column.is_custom
    )

    read = _out(client.get(path, headers=owner))
    assert not read.may_edit and "Demo" in _names(read)
    same = [{"code": c.code, "name": c.name} for c in read.columns]
    for head, refused in ((owner, 403), (lead, 404), (support, 404)):
        assert (
            client.post(path, json={"name": "Y"}, headers=head).status_code == refused
        )
        assert (
            client.patch(path, json={"columns": same}, headers=head).status_code
            == refused
        )
        assert client.delete(f"{path}/{code}", headers=head).status_code == refused
        assert (
            client.post(f"{path}/{code}/restore", headers=head).status_code == refused
        )

    me_owner = MeOut.model_validate(client.get(f"{URL}/me", headers=owner).json())
    assert me_owner.can.columns and not me_owner.can.edit_columns
    me_boss = MeOut.model_validate(client.get(f"{URL}/me", headers=boss).json())
    assert me_boss.can.columns and me_boss.can.edit_columns


def test_a_card_goes_through_a_custom_column_by_hand(
    client: TestClient, db: Session
) -> None:
    _live(db)
    _client(db, "demo@shop.test")
    triggers.sweep_sales(db, now=utcnow())
    card = db.scalar(select(BoardCard).where(BoardCard.board == "sales"))
    assert card is not None
    boss = _staff(db, "boss@office.test", superuser=True)
    path = f"{URL}/boards/sales/columns"
    code = next(
        column.code
        for column in _out(
            client.post(path, json={"name": "Demo"}, headers=boss)
        ).columns
        if column.is_custom
    )

    moved = CardDetailOut.model_validate(
        client.post(
            f"{URL}/cards/{card.id}/move",
            json={"column": code, "reason": "Demo so'radi"},
            headers=boss,
        ).json()
    )
    assert moved.column == code and moved.closed_at is None
    # No rule wrote buttons for it: the card leaves by «Ko'chirish».
    assert moved.actions == []
    board = BoardViewOut.model_validate(
        client.get(f"{URL}/boards/sales", headers=boss).json()
    )
    column = next(item for item in board.columns if item.code == code)
    assert column.is_custom
    assert [item.id for item in column.cards] == [str(card.id)]
    pressed = client.post(
        f"{URL}/cards/{card.id}/actions", json={"action": "contacted"}, headers=boss
    )
    assert pressed.status_code == 409

    # A column with a card in it stays; the sweep leaves the card there.
    held = client.delete(f"{path}/{code}", headers=boss)
    assert held.status_code == 422 and held.json()["code"] == "column_has_cards"
    triggers.sweep_sales(db, now=utcnow())
    db.refresh(card)
    assert card.column_code == code

    back = CardDetailOut.model_validate(
        client.post(
            f"{URL}/cards/{card.id}/move",
            json={"column": "contacted", "reason": "Demo o'tdi"},
            headers=boss,
        ).json()
    )
    assert back.column == "contacted" and back.history[0].from_column == code
    assert back.history[0].from_name == "Demo" and back.history[0].to_name == ""

    gone = _out(client.delete(f"{path}/{code}", headers=boss))
    assert code not in [column.code for column in gone.columns]
    assert [column.code for column in gone.removed] == [code]
    # The card's history still names the column it went through.
    after = CardDetailOut.model_validate(
        client.get(f"{URL}/cards/{card.id}", headers=boss).json()
    )
    assert after.history[0].from_name == "Demo"
    # Off the board: nothing moves there, and its name is free again.
    refused = client.post(
        f"{URL}/cards/{card.id}/move",
        json={"column": code, "reason": "x"},
        headers=boss,
    )
    assert refused.status_code == 422 and refused.json()["code"] == "no_such_column"
    again = _out(client.post(path, json={"name": "Demo"}, headers=boss))
    clash = client.post(f"{path}/{code}/restore", headers=boss)
    assert clash.status_code == 422 and clash.json()["code"] == "column_name_taken"
    twin = next(c.code for c in again.columns if c.is_custom)
    _out(client.delete(f"{path}/{twin}", headers=boss))
    restored = _out(client.post(f"{path}/{code}/restore", headers=boss))
    names = _names(restored)
    assert names.index("Demo") == names.index("Sotildi") - 1
    assert [column.code for column in restored.removed] == [twin]


def test_the_columns_the_board_came_with_are_not_taken_off(
    client: TestClient, db: Session
) -> None:
    boss = _staff(db, "boss@office.test", superuser=True)
    path = f"{URL}/boards/renewal/columns"
    client.get(path, headers=boss)
    seeded = client.delete(f"{path}/contacted", headers=boss)
    assert seeded.status_code == 422 and seeded.json()["code"] == "column_not_custom"
    unknown = client.delete(f"{path}/nothing", headers=boss)
    assert unknown.status_code == 422 and unknown.json()["code"] == "no_such_column"
